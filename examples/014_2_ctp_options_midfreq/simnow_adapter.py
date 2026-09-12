"""Fail-closed SimNow adapter for the Iteration 24 engineering smoke path.

This module is deliberately an adapter, not a CTP client.  It accepts an
already-created SDK object from a caller and never reads credentials or
``.env`` files.  The normal command-line example therefore remains offline.
External ACKs/fills are evidence supplied by the transport; this module never
creates synthetic fills.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
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
        entry = {"kind": kind, "recorded_at": datetime.now(timezone.utc).isoformat(), **dict(record)}
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
        self.confirmed: MutableMapping[str, float] = {symbol: 0.0 for symbol in symbols}
        self.status = "IDLE"
        self.recovery_required = False
        self._next_leg = 0

    def record_intent(self, basket_id: str, symbol: str, quantity: float, identity: Mapping[str, Any]) -> None:
        if self.status not in {"IDLE", "NEXT_LEG_CONFIRMED"} or symbol != self.symbols[self._next_leg]:
            raise EngineeringSmokeBlocked("INTENT_ORDER", "intent is out of sequence")
        if float(quantity) <= 0 or not basket_id:
            raise EngineeringSmokeBlocked("INTENT_ORDER", "basket and positive quantity are required")
        self._base_identity(identity)
        self.status = "INTENT"
        self.journal.append("intent", {"basket_id": basket_id, "symbol": symbol, "quantity": quantity, **dict(identity)})

    def record_ack(self, basket_id: str, symbol: str, order_id: str, client_order_id: str, identity: Mapping[str, Any]) -> None:
        self._base_identity(identity)
        if symbol != self.symbols[self._next_leg] or not order_id or not client_order_id:
            raise EngineeringSmokeBlocked("ACK_IDENTITY", "ACK requires order and client identities")
        self.status = "ACKED"
        self.journal.append("ack", {"basket_id": basket_id, "symbol": symbol, "order_id": order_id, "client_order_id": client_order_id, **dict(identity)})

    def record_fill(self, basket_id: str, symbol: str, quantity: float, identity: Mapping[str, Any]) -> None:
        self._terminal_identity(identity)
        if symbol not in self.confirmed or float(quantity) <= 0:
            raise EngineeringSmokeBlocked("FILL_IDENTITY", "fill requires a known leg and positive quantity")
        self.confirmed[symbol] += float(quantity)
        self.journal.append("fill", {"basket_id": basket_id, "symbol": symbol, "quantity": quantity, **dict(identity)})
        if self.confirmed[symbol] < 1.0:
            self.status = "PARTIAL"
            self.recovery_required = True
        elif all(value >= 1.0 for value in self.confirmed.values()):
            self.status = "COMPLETE"
        else:
            self._next_leg = self.symbols.index(symbol) + 1
            self.status = "NEXT_LEG_CONFIRMED"

    def mark_compensation(self, basket_id: str, reason: str, identity: Mapping[str, Any]) -> None:
        self._terminal_identity(identity)
        self.recovery_required = True
        self.status = "RECOVERY"
        self.journal.append("compensation_or_recovery", {"basket_id": basket_id, "reason": reason, **dict(identity)})

    @staticmethod
    def _base_identity(identity: Mapping[str, Any]) -> None:
        for key in ("account_fingerprint", "trading_day", "generation"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked("BASE_IDENTITY", f"missing base identity {key}")

    @classmethod
    def _terminal_identity(cls, identity: Mapping[str, Any]) -> None:
        cls._base_identity(identity)
        for key in ("order_id", "client_order_id"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked("TERMINAL_IDENTITY", f"missing terminal identity {key}")


_RECONCILIATION_SCHEMA = "backtrader.ctp.reconciliation.v1"
_BUNDLE_PREFLIGHT_SCHEMA = "backtrader.ctp.bundle-preflight.v2"


def _require_flat_reconciliation(item: Mapping[str, Any]) -> None:
    required = (
        "schema_version", "account_fingerprint", "trading_day", "connection_generation",
        "positions", "orders", "evidence_complete", "read_only_safe", "write_request_free",
        "active_order_count", "unknown_intent_count", "unmatched_trade_count", "flat",
    )
    if any(key not in item for key in required):
        raise EngineeringSmokeBlocked("RECONCILIATION_INCOMPLETE", "real CTP reconciliation fields are incomplete")
    if item["schema_version"] != _RECONCILIATION_SCHEMA:
        raise EngineeringSmokeBlocked("RECONCILIATION_SCHEMA", "unsupported CTP reconciliation schema")
    if any(item[key] is not True for key in ("evidence_complete", "read_only_safe", "write_request_free", "flat")):
        raise EngineeringSmokeBlocked("RECONCILIATION_NOT_FLAT", "CTP reconciliation is not complete, read-only, or flat")
    if any(item[key] != 0 for key in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")):
        raise EngineeringSmokeBlocked("RECONCILIATION_NOT_FLAT", "CTP reconciliation contains active or unknown execution state")


def require_two_account_reconciliations(rounds: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Require two real v1, complete, same-identity, flat observations."""

    materialized = tuple(rounds)
    if len(materialized) != 2:
        raise EngineeringSmokeBlocked("RECONCILIATION_ROUNDS", "exactly two reconciliation rounds are required")
    for item in materialized:
        _require_flat_reconciliation(item)
    identity = tuple(materialized[0][key] for key in ("account_fingerprint", "trading_day", "connection_generation"))
    if any(tuple(item[key] for key in ("account_fingerprint", "trading_day", "connection_generation")) != identity for item in materialized[1:]):
        raise EngineeringSmokeBlocked("RECONCILIATION_IDENTITY", "reconciliation identity changed")
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
