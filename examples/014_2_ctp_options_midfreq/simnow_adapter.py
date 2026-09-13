"""Fail-closed SimNow adapter for the Iteration 24 engineering smoke path.

This module is deliberately an adapter, not a CTP client.  It accepts an
already-created SDK object from a caller and never reads credentials or
``.env`` files.  The normal command-line example therefore remains offline.
External ACKs/fills are evidence supplied by the transport; this module never
creates synthetic fills.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional

import backtrader as bt
from backtrader.stores.btapistore import BtApiStore


class EngineeringSmokeBlocked(RuntimeError):
    """A missing safety prerequisite; no external action was attempted."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
            raise EngineeringSmokeBlocked("FEE_MARGIN_MISSING", "fee and margin sources are required")
        if set(self.fee_by_leg) != expected or set(self.margin_by_leg) != expected:
            raise EngineeringSmokeBlocked("FEE_MARGIN_INCOMPLETE", "fee/margin must cover all legs")
        if any(float(value) < 0 for value in self.fee_by_leg.values()) or any(
            float(value) < 0 for value in self.margin_by_leg.values()
        ):
            raise EngineeringSmokeBlocked("FEE_MARGIN_INVALID", "fee/margin values must be non-negative")
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
        if self.status not in {"IDLE", "NEXT_LEG_CONFIRMED"} or symbol != self.symbols[self._next_leg]:
            raise EngineeringSmokeBlocked("INTENT_ORDER", "intent is out of sequence")
        quantity_value = self._positive_finite_quantity(quantity, "INTENT_ORDER")
        if not basket_id or not client_order_id:
            raise EngineeringSmokeBlocked(
                "INTENT_ORDER", "basket, client order ID, and positive quantity are required"
            )
        identity_key = self._identity_key(identity)
        if self._active_basket_id is not None and basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked("INTENT_BASKET", "intent basket does not match active basket")
        if self._active_identity is not None and identity_key != self._active_identity:
            raise EngineeringSmokeBlocked("INTENT_IDENTITY", "intent identity does not match active basket")
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

    def record_ack(self, basket_id: str, symbol: str, order_id: str, client_order_id: str, identity: Mapping[str, Any]) -> None:
        self._require_writable_evidence()
        identity_key = self._identity_key(identity)
        if self.status != "INTENT" or self._intent_symbol != symbol:
            raise EngineeringSmokeBlocked("ACK_ORDER", "ACK requires the pending intent leg")
        if basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked("ACK_BASKET", "ACK basket does not match active basket")
        if identity_key != self._active_identity:
            raise EngineeringSmokeBlocked("ACK_IDENTITY", "ACK identity does not match active basket")
        if symbol != self.symbols[self._next_leg] or not order_id or not client_order_id:
            raise EngineeringSmokeBlocked("ACK_IDENTITY", "ACK requires order and client identities")
        if str(client_order_id) != self._intent_client_order_id:
            raise EngineeringSmokeBlocked("ACK_IDENTITY", "ACK client order ID does not match the intent")
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

    def record_fill(self, basket_id: str, symbol: str, quantity: float, identity: Mapping[str, Any]) -> None:
        self._require_writable_evidence()
        identity_key, trade_key = self._fill_identity(identity, symbol)
        if self.status not in {"ACKED", "PARTIAL", "RECOVERY"} or self._intent_symbol != symbol:
            raise EngineeringSmokeBlocked("FILL_ORDER", "fill requires the acknowledged pending leg")
        if basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked("FILL_BASKET", "fill basket does not match active basket")
        if identity_key != self._active_identity:
            raise EngineeringSmokeBlocked("FILL_IDENTITY", "fill identity does not match active basket")
        if (
            str(identity["order_id"]) != self._ack_order_id
            or str(identity["client_order_id"]) != self._ack_client_order_id
        ):
            raise EngineeringSmokeBlocked("FILL_IDENTITY", "fill identities do not match the acknowledged order")
        if trade_key in self._seen_trade_keys:
            raise EngineeringSmokeBlocked("FILL_DUPLICATE", "fill trade ID was already recorded")
        quantity_value = self._positive_finite_quantity(quantity, "FILL_QUANTITY")
        if symbol not in self.confirmed or self._intent_quantity is None:
            raise EngineeringSmokeBlocked("FILL_IDENTITY", "fill requires a known leg and pending quantity")
        confirmed_quantity = self.confirmed[symbol] + quantity_value
        if not math.isfinite(confirmed_quantity) or confirmed_quantity > self._intent_quantity:
            raise EngineeringSmokeBlocked("FILL_QUANTITY", "fill quantity exceeds the pending intent")
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
                "RECOVERY_ORDER", "recovery requires an acknowledged or partially filled pending leg"
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
        return tuple(str(identity[key]) for key in ("account_fingerprint", "trading_day", "generation"))

    @staticmethod
    def _positive_finite_quantity(quantity: float, code: str) -> float:
        try:
            quantity_value = float(quantity)
        except (TypeError, ValueError, OverflowError) as error:
            raise EngineeringSmokeBlocked(code, "quantity must be a finite positive number") from error
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
                "EVIDENCE_FAILURE", "journal evidence previously failed; recovery is externally required"
            )

    @classmethod
    def _terminal_identity(cls, identity: Mapping[str, Any]) -> tuple[str, str, str]:
        identity_key = cls._identity_key(identity)
        for key in ("order_id", "client_order_id"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked("TERMINAL_IDENTITY", f"missing terminal identity {key}")
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
        "schema_version", "account_fingerprint", "trading_day", "connection_generation",
        "account", "positions", "orders", "trades", "complete", "is_last_seen", "timed_out",
        "error_code", "evidence_complete", "read_only_safe", "write_request_free",
        "active_order_count", "unknown_intent_count", "unmatched_trade_count", "flat",
    )
    if any(key not in item for key in required):
        raise EngineeringSmokeBlocked("RECONCILIATION_INCOMPLETE", "real CTP reconciliation fields are incomplete")
    if item["schema_version"] != _RECONCILIATION_SCHEMA:
        raise EngineeringSmokeBlocked("RECONCILIATION_SCHEMA", "unsupported CTP reconciliation schema")
    if (
        not isinstance(item["account_fingerprint"], str)
        or not item["account_fingerprint"].strip()
        or not isinstance(item["trading_day"], str)
        or not item["trading_day"].strip()
        or type(item["connection_generation"]) is not int
        or item["connection_generation"] <= 0
    ):
        raise EngineeringSmokeBlocked("RECONCILIATION_IDENTITY", "CTP reconciliation identity is invalid")
    if (
        item["complete"] is not True
        or item["is_last_seen"] is not True
        or item["timed_out"] is not False
        or item["error_code"] not in (None, "", 0, "0")
        or any(not isinstance(item[key], (list, tuple)) for key in ("account", "positions", "orders", "trades"))
    ):
        raise EngineeringSmokeBlocked("RECONCILIATION_INCOMPLETE", "CTP reconciliation scope is incomplete")
    if any(item[key] is not True for key in ("evidence_complete", "read_only_safe", "write_request_free", "flat")):
        raise EngineeringSmokeBlocked("RECONCILIATION_NOT_FLAT", "CTP reconciliation is not complete, read-only, or flat")
    if any(item[key] != 0 for key in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")):
        raise EngineeringSmokeBlocked("RECONCILIATION_NOT_FLAT", "CTP reconciliation contains active or unknown execution state")
    return _reconciliation_request_id_scope(item)


def require_two_account_reconciliations(rounds: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Require two real v1, complete, same-identity, flat observations."""

    materialized = tuple(rounds)
    if len(materialized) != 2:
        raise EngineeringSmokeBlocked("RECONCILIATION_ROUNDS", "exactly two reconciliation rounds are required")
    request_id_scopes = tuple(_require_flat_reconciliation(item) for item in materialized)
    identity = tuple(materialized[0][key] for key in ("account_fingerprint", "trading_day", "connection_generation"))
    if any(tuple(item[key] for key in ("account_fingerprint", "trading_day", "connection_generation")) != identity for item in materialized[1:]):
        raise EngineeringSmokeBlocked("RECONCILIATION_IDENTITY", "reconciliation identity changed")
    if _stable_reconciliation_fingerprint(materialized[0]) != _stable_reconciliation_fingerprint(materialized[1]):
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

    def startup(self, legs: Any, *, primary_leg: Any = None, timeout: float = 15.0) -> dict[str, Any]:
        bundle = self.store.get_ctp_bundle_preflight_snapshot(
            legs, primary_leg=primary_leg, timeout=timeout, read_only=True
        )
        required = ("schema_version", "evidence_complete", "read_only_safe", "flat")
        if any(key not in bundle for key in required) or bundle["schema_version"] != _BUNDLE_PREFLIGHT_SCHEMA:
            raise EngineeringSmokeBlocked("BUNDLE_PREFLIGHT_SCHEMA", "unsupported or incomplete CTP bundle preflight")
        if any(bundle[key] is not True for key in ("evidence_complete", "read_only_safe", "flat")):
            raise EngineeringSmokeBlocked("BUNDLE_PREFLIGHT_NOT_FLAT", "CTP bundle preflight is not complete, read-only, or flat")
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
            raise EngineeringSmokeBlocked("SETTLEMENT_NOT_VERIFIED", "public Store settlement verification is incomplete")
        return result

    def prepare_settlement(self, *, timeout: float = 5.0) -> Mapping[str, Any]:
        """Explicit operator action; never called by engineering_smoke."""
        result = self.store.prepare_ctp_settlement(timeout=timeout)
        if not result.get("evidence_complete"):
            raise EngineeringSmokeBlocked("SETTLEMENT_NOT_PREPARED", "public Store settlement preparation is incomplete")
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


def build_engineering_smoke(*, config: Mapping[str, Any], api: Any = None, journal_path: Optional[Path] = None) -> dict[str, Any]:
    """Build the sole native chain without starting a session or writing orders."""

    if api is None:
        raise EngineeringSmokeBlocked("SDK_NOT_INJECTED", "engineering_smoke requires an explicit API object")
    candidate = config["candidate"]
    symbols = tuple(candidate["contracts"][field] for field in ("future", "call", "put"))
    # Live SimNow is the managed bt_api_py session.  The CTP wrapper is still
    # owned by BtApiStore; no native Trader/MarketData client is constructed
    # here or passed around separately.
    store = BtApiStore(provider="btapi", api=api, config={"market_data_only": True}, autostart=False)
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
        "external_trade_writes": 0,
        "chain": {"store": type(store).__name__, "feeds": [type(feed).__name__ for feed in feeds], "broker": type(broker).__name__, "cerebro": type(cerebro).__name__},
        "symbols": symbols,
        "journal_path": str(journal_path) if journal_path else None,
        "orders_submitted": 0,
        "fills_created": 0,
        "market_data_only": True,
        "execution_permission": "NOT_PROVEN",
    }
