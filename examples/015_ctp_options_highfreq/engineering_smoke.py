"""Fail-closed SimNow engineering-smoke adapter for Iteration 25.

This module is deliberately an adapter, not a SimNow client.  A caller must
inject an already configured ``BtApiStore`` (normally backed by a test
transport).  The adapter never reads environment variables, starts a socket,
or submits an order during construction.  It exists to exercise the causal
object graph and the native lifecycle/reconciliation rules before a separately
approved external run.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.feeds.ctpcohort import CtpCohortNow
from backtrader.stores.btapistore import BtApiStore


class EngineeringSmokeError(RuntimeError):
    """A fail-closed engineering-smoke rejection."""


@dataclass(frozen=True)
class SessionIdentity:
    account_fingerprint: str
    trading_day: str
    generation: int
    subscription_epoch: int
    clock_domain_id: str


@dataclass(frozen=True)
class NativeAssociation:
    cycle_id: str
    intent_id: str
    bt_order_ref: str
    sdk_order_id: str = ""
    front_id: int = 0
    session_id: int = 0
    order_ref: str = ""
    exchange_id: str = ""
    order_sys_id: str = ""
    trade_id: str = ""
    generation: int = 0
    symbol: str = ""
    side: str = ""
    offset: str = "open"
    requested_volume: int = 1
    cumulative_fill: int = 0


@dataclass
class SmokeState:
    status: str = "DISARMED"
    hft_status: str = "NOT_ADMITTED"
    ordinary_entry_blocked: bool = True
    reason: str = "ENGINEERING_SMOKE_REQUIRES_EXPLICIT_ARMING"
    cycle_id: str = ""
    write_attempts: int = 0
    ordinary_attempts: int = 0
    safety_attempts: int = 0
    actual_fills: int = 0
    unknown_events: int = 0
    associations: list[NativeAssociation] = field(default_factory=list)
    classifications: list[str] = field(default_factory=list)
    reconciliation_rounds: int = 0


class AppendOnlyJournal:
    """Small JSONL journal; each lifecycle event is persisted before progress."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, **fields: Any) -> None:
        record = {"schema_version": "iter25.ctp-options-engineering-journal.v1", "event": event}
        record.update(fields)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class _SmokeStrategy(bt.Strategy):
    """Only forwards native strategy callbacks to the adapter."""

    def __init__(self, adapter: "EngineeringSmokeAdapter") -> None:
        self._engineering_smoke_adapter = adapter

    def notify_tick(self, tick: Any) -> None:
        self._engineering_smoke_adapter.on_tick(tick)

    def notify_order(self, order: Any) -> None:
        self._engineering_smoke_adapter.on_order_event(order)

    def notify_trade(self, trade: Any) -> None:
        self._engineering_smoke_adapter.on_trade_event(trade)


class EngineeringSmokeAdapter:
    """Controlled one-cycle lifecycle around the native Backtrader chain.

    ``store`` is mandatory and must be supplied by the caller.  A fake Store
    or injected SDK transport is therefore testable, while accidentally
    turning this example into a network runner is impossible by construction.
    """

    MAX_WRITES = 100
    MAX_ORDINARY = 80
    SAFETY_RESERVE = 20
    MAX_ORDINARY_PER_SECOND = 2

    def __init__(
        self,
        *,
        store: BtApiStore,
        symbols: Iterable[str],
        session: SessionIdentity,
        journal: AppendOnlyJournal,
        now_ns: Callable[[], int] = time.monotonic_ns,
        starting_cash: float = 10_000.0,
    ) -> None:
        if not isinstance(store, BtApiStore):
            raise EngineeringSmokeError("BTAPISTORE_REQUIRED")
        self.store = store
        self.symbols = tuple(str(symbol) for symbol in symbols)
        if len(self.symbols) != 3 or len(set(self.symbols)) != 3:
            raise EngineeringSmokeError("EXACTLY_THREE_DISTINCT_LEGS_REQUIRED")
        self.session = session
        self.journal = journal
        self._now_ns = now_ns
        self._rate_window: deque[int] = deque()
        self._last_tick: Optional[tuple[int, str]] = None
        self._reconciliation_fingerprint: Optional[str] = None
        self._authorization_verified = False
        self._bundle_preflight_verified = False
        self._settlement_verified = False
        self._seen_trade_ids: set[str] = set()
        self.state = SmokeState()

        # This is the only construction path for the engineering-smoke graph.
        self.cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        self.broker = self.store.getbroker()
        self.cerebro.setbroker(self.broker)
        self.feed = tuple(
            self.store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Ticks,
                dispatch_ticks=True,
                dispatch_bars=False,
                backfill_start=False,
                ctp_decision_now_provider=self._decision_now_provider,
            )
            for symbol in self.symbols
        )
        for data in self.feed:
            self.cerebro.adddata(data)
        self.cerebro.addstrategy(_SmokeStrategy, adapter=self)
        self.journal.append(
            "chain_built",
            chain={
                "store": _type_name(self.store),
                "feed": [_type_name(item) for item in self.feed],
                "broker": _type_name(self.broker),
                "cerebro": _type_name(self.cerebro),
            },
            hft_status="NOT_ADMITTED",
            starting_cash=starting_cash,
        )

    @property
    def runtime_chain(self) -> dict[str, Any]:
        return {
            "store": _type_name(self.store),
            "feed": [_type_name(item) for item in self.feed],
            "broker": _type_name(self.broker),
            "cerebro": _type_name(self.cerebro),
            "strategy": _type_name(_SmokeStrategy),
        }

    def _decision_now_provider(self, tick: Any) -> CtpCohortNow:
        """Require an explicit same-domain clock; never use process time."""
        now = getattr(tick, "cohort_now", None)
        if not isinstance(now, CtpCohortNow):
            raise EngineeringSmokeError("TRUSTED_COHORT_NOW_REQUIRED")
        if now.clock_domain_id != self.session.clock_domain_id:
            raise EngineeringSmokeError("CLOCK_DOMAIN_MISMATCH")
        return now

    def on_tick(self, tick: Any) -> None:
        generation = getattr(tick, "connection_generation", None)
        domain = getattr(tick, "clock_domain_id", None)
        if (
            generation != self.session.generation
            or getattr(tick, "subscription_epoch", None) != self.session.subscription_epoch
            or getattr(tick, "trading_day", None) != self.session.trading_day
            or domain != self.session.clock_domain_id
        ):
            self._block("COHORT_EPOCH_INVALID")
            return
        if not isinstance(getattr(tick, "cohort_now", None), CtpCohortNow):
            self._block("TRUSTED_COHORT_NOW_REQUIRED")
            return
        self._last_tick = (int(getattr(tick, "ingest_seq", 0)), str(getattr(tick, "symbol", "")))
        self.journal.append("tick_observed", generation=generation, symbol=self._last_tick[1], ingest_seq=self._last_tick[0])

    def get_bundle_preflight(self, legs: Iterable[Mapping[str, Any]], *, timeout: float = 15.0) -> dict[str, Any]:
        """Use the Store-owned read-only bundle preflight; never inspect its client."""
        try:
            snapshot = self.store.get_ctp_bundle_preflight_snapshot(
                list(legs), timeout=timeout, read_only=True
            )
        except Exception as exc:
            self._block("BUNDLE_PREFLIGHT_UNAVAILABLE")
            raise EngineeringSmokeError("BUNDLE_PREFLIGHT_UNAVAILABLE") from exc
        if not isinstance(snapshot, Mapping):
            self._block("BUNDLE_PREFLIGHT_INVALID")
            raise EngineeringSmokeError("BUNDLE_PREFLIGHT_INVALID")
        if not _valid_preflight_snapshot(snapshot, self.session):
            self._block("BUNDLE_PREFLIGHT_NOT_SAFE")
            raise EngineeringSmokeError("BUNDLE_PREFLIGHT_NOT_SAFE")
        self._bundle_preflight_verified = True
        self.journal.append(
            "bundle_preflight",
            snapshot_sha256=str(snapshot.get("snapshot_sha256") or ""),
            complete=bool(snapshot.get("complete", snapshot.get("evidence_complete", False))),
            generation=snapshot.get("connection_generation"),
            trading_day=snapshot.get("trading_day"),
        )
        return dict(snapshot)

    def reconcile_from_store(self, *, timeout: float = 5.0) -> bool:
        """Collect one Store-owned complete snapshot and apply the two-round gate."""
        try:
            snapshot = self.store.get_ctp_reconciliation_snapshot(timeout=timeout)
        except Exception as exc:
            self._unknown("RECONCILIATION_QUERY_FAILED")
            raise EngineeringSmokeError("RECONCILIATION_QUERY_FAILED") from exc
        return self.reconcile(snapshot)

    def verify_settlement(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Delegate settlement verification to the public Store API only."""
        try:
            result = self.store.verify_ctp_settlement(timeout=timeout)
        except Exception as exc:
            self._unknown("SETTLEMENT_VERIFICATION_FAILED")
            raise EngineeringSmokeError("SETTLEMENT_VERIFICATION_FAILED") from exc
        self._settlement_verified = bool(
            isinstance(result, Mapping)
            and result.get("success") is True
            and result.get("evidence_complete") is True
        )
        self.journal.append(
            "settlement_verified",
            evidence_complete=bool(result.get("evidence_complete")) if isinstance(result, Mapping) else False,
        )
        return dict(result)

    def prepare_settlement(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Expose the explicit Store settlement write without auto-invoking it."""
        try:
            result = self.store.prepare_ctp_settlement(timeout=timeout)
        except Exception as exc:
            self._unknown("SETTLEMENT_PREPARATION_FAILED")
            raise EngineeringSmokeError("SETTLEMENT_PREPARATION_FAILED") from exc
        self._settlement_verified = bool(
            isinstance(result, Mapping)
            and result.get("success") is True
            and result.get("evidence_complete") is True
        )
        self.journal.append(
            "settlement_prepared",
            evidence_complete=bool(result.get("evidence_complete")) if isinstance(result, Mapping) else False,
        )
        return dict(result)

    def configure_execution_authorization(self, grant: Mapping[str, Any]) -> dict[str, Any]:
        """Delegate authorization verification; grant contents never enter the journal."""
        try:
            result = self.store.configure_ctp_execution_authorization(grant)
        except Exception as exc:
            self._block("EXECUTION_AUTHORIZATION_UNAVAILABLE")
            raise EngineeringSmokeError("EXECUTION_AUTHORIZATION_UNAVAILABLE") from exc
        if not isinstance(result, Mapping) or result.get("configured") is not True:
            self._block("EXECUTION_AUTHORIZATION_NOT_CONFIGURED")
            raise EngineeringSmokeError("EXECUTION_AUTHORIZATION_NOT_CONFIGURED")
        self._authorization_verified = True
        self.journal.append("execution_authorization_verified", configured=True)
        return dict(result)

    def arm_one_cycle(self, *, cycle_id: str, intent_id: str) -> None:
        if self.state.status not in {"DISARMED", "FLAT_VERIFIED"}:
            raise EngineeringSmokeError("CYCLE_ALREADY_ARMED_OR_CONSUMED")
        if not self._authorization_verified:
            raise EngineeringSmokeError("CTP_EXECUTION_TRUST_ROOT_UNAVAILABLE")
        if not self._settlement_verified:
            raise EngineeringSmokeError("CTP_SETTLEMENT_NOT_VERIFIED")
        if not self._bundle_preflight_verified:
            raise EngineeringSmokeError("CTP_BUNDLE_PREFLIGHT_NOT_VERIFIED")
        if self.state.reconciliation_rounds < 2 or self.state.status != "FLAT_VERIFIED":
            raise EngineeringSmokeError("CTP_TWO_ROUND_RECONCILIATION_REQUIRED")
        self.state.status = "READY"
        self.state.cycle_id = cycle_id
        self.journal.append("cycle_armed", cycle_id=cycle_id, intent_id=intent_id, generation=self.session.generation)

    def authorize_one_lot_write(self, *, safety: bool = False) -> None:
        """Reserve one write budget unit; callers still need native Broker calls."""
        if self.state.status not in {"READY", "ENTERING", "EXITING", "RECOVERING"}:
            raise EngineeringSmokeError("CYCLE_NOT_READY")
        if self.state.write_attempts >= self.MAX_WRITES:
            self._block("RATE_BUDGET_UNAVAILABLE")
            raise EngineeringSmokeError("RATE_BUDGET_UNAVAILABLE")
        if not safety and self.state.ordinary_attempts >= self.MAX_ORDINARY:
            self._block("ORDINARY_RATE_BUDGET_UNAVAILABLE")
            raise EngineeringSmokeError("ORDINARY_RATE_BUDGET_UNAVAILABLE")
        if safety and self.state.safety_attempts >= self.SAFETY_RESERVE:
            raise EngineeringSmokeError("SAFETY_RATE_BUDGET_UNAVAILABLE")
        now = self._now_ns()
        while self._rate_window and now - self._rate_window[0] >= 1_000_000_000:
            self._rate_window.popleft()
        if not safety and len(self._rate_window) >= self.MAX_ORDINARY_PER_SECOND:
            self._block("ORDINARY_RATE_LIMIT")
            raise EngineeringSmokeError("ORDINARY_RATE_LIMIT")
        self._rate_window.append(now)
        self.state.write_attempts += 1
        if safety:
            self.state.safety_attempts += 1
        else:
            self.state.ordinary_attempts += 1
        self.journal.append("write_reserved", safety=safety, write_attempts=self.state.write_attempts)

    def record_send(self, association: NativeAssociation) -> None:
        if (
            association.generation != self.session.generation
            or association.requested_volume != 1
            or association.cycle_id != self.state.cycle_id
            or any(item.bt_order_ref == association.bt_order_ref for item in self.state.associations)
        ):
            self._block("NATIVE_ASSOCIATION_INVALID")
            raise EngineeringSmokeError("NATIVE_ASSOCIATION_INVALID")
        self.journal.append("send", association=asdict(association))
        self.state.associations.append(association)
        self.state.status = "ENTERING"

    def request_cancel(self, *, order_ref: str) -> None:
        """Issue only a safety-budgeted cancel intent; it never clears fill risk."""
        self.authorize_one_lot_write(safety=True)
        self.state.status = "CANCEL_PENDING"
        self.journal.append("cancel_send", order_ref=order_ref)

    def on_order_event(self, event: Any) -> str:
        status = str(getattr(event, "status", getattr(event, "Status", ""))).lower()
        if status in {"unknown", "rejected", "error"}:
            self._unknown("EXECUTION_UNKNOWN")
        elif status in {"accepted", "submitted", "ack"}:
            self.journal.append("ack", status=status, order_ref=_event_id(event))
        elif status in {"canceled", "cancelled"}:
            self.journal.append("cancel_ack", order_ref=_event_id(event))
        elif status in {"partial", "completed", "filled"}:
            self.journal.append("order_terminal", status=status, order_ref=_event_id(event))
        return self.state.status

    def on_trade_event(self, trade: Any) -> str:
        trade_id = str(getattr(trade, "trade_id", getattr(trade, "TradeID", "")) or "")
        if not trade_id:
            self._unknown("TRADE_ID_MISSING")
            return self.state.status
        if trade_id in self._seen_trade_ids:
            self.journal.append("duplicate_trade", trade_id=trade_id)
            return self.state.status
        self._seen_trade_ids.add(trade_id)
        if self.state.status in {"RECOVERING", "UNKNOWN", "HALTED_MONITORING"}:
            self.state.classifications.append("late_fill")
            self.journal.append("late_fill", trade_id=trade_id)
        elif self.state.status == "CANCEL_PENDING":
            self.state.classifications.append("cancel_before_trade")
            self.journal.append("cancel_before_trade", trade_id=trade_id)
        else:
            self.state.actual_fills += 1
            if self.state.status == "ENTERING" and not any(
                item.bt_order_ref == _event_id(trade) for item in self.state.associations
            ):
                self.state.classifications.append("trade_before_ack")
            self.journal.append("fill", trade_id=trade_id, actual_fill=True)
        return self.state.status

    def on_reconnect(self, *, session: SessionIdentity) -> None:
        if session.generation <= self.session.generation:
            self._block("STALE_CONNECTION_GENERATION")
            return
        self.session = session
        self.state.status = "RECOVERING"
        self.state.ordinary_entry_blocked = True
        self.state.reason = "RECONNECT_REQUIRES_TWO_ROUND_RECONCILIATION"
        self.state.classifications.append("reconnect_generation_change")
        self.journal.append("reconnect", generation=session.generation)

    def reconcile(self, snapshot: Mapping[str, Any]) -> bool:
        snapshot = _normalize_reconciliation_snapshot(snapshot)
        if not _valid_reconciliation_snapshot(snapshot, self.session):
            self.state.reconciliation_rounds = 0
            self._reconciliation_fingerprint = None
            self._unknown("RECONCILIATION_NOT_SAFE")
            return False
        fingerprint = _stable_reconciliation_fingerprint(snapshot)
        if self._reconciliation_fingerprint != fingerprint:
            self._reconciliation_fingerprint = fingerprint
            self.state.reconciliation_rounds = 1
        else:
            self.state.reconciliation_rounds += 1
        self.journal.append("reconciliation", round=self.state.reconciliation_rounds, generation=self.session.generation)
        if self.state.reconciliation_rounds < 2:
            return False
        self.state.status = "FLAT_VERIFIED" if not snapshot["positions"] and not snapshot["orders"] else "RECONCILING"
        return self.state.status == "FLAT_VERIFIED"

    def report(self) -> dict[str, Any]:
        return {
            "status": self.state.status,
            "hft_status": "NOT_ADMITTED",
            "ordinary_entry_blocked": self.state.ordinary_entry_blocked,
            "market_data_only": not self._authorization_verified,
            "execution_authorized": self._authorization_verified,
            "reason": self.state.reason,
            "runtime_chain": self.runtime_chain,
            "actual_fills": self.state.actual_fills,
            "pnl_fields_emitted": False,
            "external_network_requests": 0,
            "external_write_requests": 0,
            "reconciliation_rounds": self.state.reconciliation_rounds,
            "classifications": list(self.state.classifications),
        }

    def _block(self, reason: str) -> None:
        self.state.ordinary_entry_blocked = True
        self.state.reason = reason
        self.state.status = "HALTED_MONITORING"
        self.journal.append("blocked", reason=reason)

    def _unknown(self, reason: str) -> None:
        self.state.unknown_events += 1
        self.state.status = "UNKNOWN"
        self.state.ordinary_entry_blocked = True
        self.state.reason = reason
        self.state.classifications.append(reason)
        self.journal.append("unknown", reason=reason)


def _type_name(value: Any) -> str:
    if isinstance(value, type):
        return f"{value.__module__}.{value.__name__}"
    return f"{type(value).__module__}.{type(value).__name__}"


def _event_id(value: Any) -> str:
    return str(getattr(value, "order_ref", getattr(value, "ref", "")) or "")


def _normalize_reconciliation_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Map the public Store naming to the adapter's small, typed gate."""
    normalized = dict(snapshot)
    if "generation" not in normalized:
        normalized["generation"] = normalized.get("connection_generation")
    normalized.setdefault("trading_day", normalized.get("TradingDay"))
    return normalized


_VOLATILE_EVIDENCE_KEYS = frozenset(
    {
        "captured_at",
        "requested_at_utc",
        "received_at_utc",
        "requested_monotonic",
        "received_monotonic",
        "request_ids",
        "all_request_ids",
        "snapshot_sha256",
    }
)


def _stable_evidence_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_evidence_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in _VOLATILE_EVIDENCE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_evidence_value(item) for item in value]
    return value


def _stable_reconciliation_fingerprint(snapshot: Mapping[str, Any]) -> str:
    """Fingerprint safety semantics, excluding query timestamps/request IDs."""
    fields = (
        "schema_version",
        "account_fingerprint",
        "trading_day",
        "connection_generation",
        "evidence_complete",
        "read_only_safe",
        "write_request_free",
        "flat",
        "active_order_count",
        "unknown_intent_count",
        "unmatched_trade_count",
        "account",
        "positions",
        "orders",
        "trades",
    )
    material = {field: _stable_evidence_value(snapshot.get(field)) for field in fields}
    return json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _valid_identity(snapshot: Mapping[str, Any], session: SessionIdentity) -> bool:
    return (
        snapshot.get("account_fingerprint") == session.account_fingerprint
        and snapshot.get("trading_day") == session.trading_day
        and snapshot.get("connection_generation") == session.generation
    )


def _valid_preflight_snapshot(snapshot: Mapping[str, Any], session: SessionIdentity) -> bool:
    return (
        snapshot.get("evidence_complete") is True
        and snapshot.get("read_only_safe") is True
        and snapshot.get("flat") is True
        and _valid_identity(snapshot, session)
    )


def _valid_reconciliation_snapshot(snapshot: Mapping[str, Any], session: SessionIdentity) -> bool:
    return (
        snapshot.get("schema_version") == "backtrader.ctp.reconciliation.v1"
        and snapshot.get("evidence_complete") is True
        and snapshot.get("read_only_safe") is True
        and snapshot.get("write_request_free") is True
        and snapshot.get("flat") is True
        and snapshot.get("active_order_count") == 0
        and snapshot.get("unknown_intent_count") == 0
        and snapshot.get("unmatched_trade_count") == 0
        and _valid_identity(snapshot, session)
    )


__all__ = [
    "AppendOnlyJournal",
    "EngineeringSmokeAdapter",
    "EngineeringSmokeError",
    "NativeAssociation",
    "SessionIdentity",
]
