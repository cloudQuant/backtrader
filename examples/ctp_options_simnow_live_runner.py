"""Governed, injected launcher for the Iter23/24/25 CTP mechanical smoke.

Importing this module is deliberately inert: it does not read the environment,
construct a client, connect, or submit an order.  A caller supplies the one
Store, broker, feeds, public evidence, and (only when explicitly requested) an
already armed authorization proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Mapping

from .ctp_options_simnow_common import ThreeLegBundle, select_three_leg_bundle
from .ctp_options_simnow_mechanical_cycle import (
    MechanicalCycle,
    MechanicalCycleBlocked,
    MechanicalLeg,
    _identity,
    _semantic_hash,
    _strict_snapshot,
)


class SimNowLiveRunnerBlocked(RuntimeError):
    """The injected evidence or public capability is not safe to use."""


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SimNowLiveRunnerBlocked(f"{name}_MISSING")
    return value.strip()


def _redact_snapshot(snapshot: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Keep status evidence without emitting account or native payloads."""
    identity = _identity(snapshot, label)
    semantic_hash = (
        _semantic_hash(snapshot)
        if all(
            key in snapshot
            for key in (
                "flat",
                "active_order_count",
                "unknown_intent_count",
                "unmatched_trade_count",
            )
        )
        else _hash(snapshot)
    )
    return {
        "label": label,
        "account_fingerprint_sha256": _hash(identity[0]),
        "trading_day": identity[1],
        "connection_generation": identity[2],
        "semantic_hash": semantic_hash,
        "evidence_complete": snapshot.get("evidence_complete") is True,
        "read_only_safe": snapshot.get("read_only_safe") is True,
        "write_request_free": snapshot.get("write_request_free") is True,
        "flat": snapshot.get("flat") is True,
        "active_order_count": snapshot.get("active_order_count"),
        "unknown_intent_count": snapshot.get("unknown_intent_count"),
        "unmatched_trade_count": snapshot.get("unmatched_trade_count"),
    }


def _strict_stage(snapshot: Any, label: str) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise SimNowLiveRunnerBlocked(f"{label}_SCHEMA_INVALID")
    required = ("evidence_complete", "read_only_safe", "write_request_free")
    if any(snapshot.get(key) is not True for key in required):
        raise SimNowLiveRunnerBlocked(f"{label}_NOT_READ_ONLY_COMPLETE")
    try:
        _identity(snapshot, label)
    except MechanicalCycleBlocked as exc:
        raise SimNowLiveRunnerBlocked(str(exc)) from exc
    return dict(snapshot)


def _scope_value(snapshot: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in snapshot:
            return snapshot[name]
    return None


def _authorization_ready(authorization: Any) -> dict[str, Any]:
    if not isinstance(authorization, Mapping):
        raise SimNowLiveRunnerBlocked("HMAC_GRANT_REQUIRED")
    if authorization.get("armed") is not True:
        raise SimNowLiveRunnerBlocked("HMAC_GRANT_NOT_ARMED")
    if (
        authorization.get("hmac_grant_configured") is not True
        and authorization.get("grant_configured") is not True
    ):
        raise SimNowLiveRunnerBlocked("HMAC_GRANT_NOT_CONFIGURED")
    signature = authorization.get("signature_hmac_sha256")
    nested_grant = authorization.get("grant")
    if signature in (None, "") and isinstance(nested_grant, Mapping):
        signature = nested_grant.get("signature_hmac_sha256")
    if not isinstance(signature, str) or not signature.strip():
        raise SimNowLiveRunnerBlocked("HMAC_GRANT_SIGNATURE_MISSING")
    # Return only booleans/identity fields needed by MechanicalCycle; never copy
    # a secret or a full grant into the journal.
    return {
        "armed": True,
        "account_fingerprint": authorization.get("account_fingerprint"),
        "connection_generation": authorization.get("connection_generation"),
    }


def _bundle_leg_identities(snapshot: Mapping[str, Any]) -> tuple[tuple[str, str, bool], ...]:
    legs = snapshot.get("legs")
    if not isinstance(legs, list) or len(legs) != 3:
        raise SimNowLiveRunnerBlocked("THREE_LEG_BUNDLE_REQUIRED")
    result = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            raise SimNowLiveRunnerBlocked("BUNDLE_LEG_SCHEMA_INVALID")
        result.append(
            (
                _text(leg.get("exchange_id"), "bundle.exchange_id"),
                _text(leg.get("instrument_id"), "bundle.instrument_id"),
                leg.get("is_primary") is True,
            )
        )
    return tuple(result)


def _identity_hash(snapshot: Mapping[str, Any]) -> str:
    return _hash(
        {
            "account_fingerprint": snapshot["account_fingerprint"],
            "trading_day": snapshot["trading_day"],
            "connection_generation": snapshot["connection_generation"],
        }
    )


def _legs_hash(legs: tuple[tuple[str, str, bool], ...]) -> str:
    return _hash([list(item) for item in legs])


def _bundle_scope_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the Store's compact bundle scope from a validated full proof."""
    legs = snapshot.get("legs")
    if not isinstance(legs, list):
        raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_BUNDLE_SCOPE_INVALID")
    primary = [leg for leg in legs if isinstance(leg, Mapping) and leg.get("is_primary") is True]
    if len(primary) != 1:
        raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_BUNDLE_SCOPE_INVALID")
    qualified = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_BUNDLE_SCOPE_INVALID")
        exchange = _text(leg.get("exchange_id"), "bundle.exchange_id")
        instrument = _text(leg.get("instrument_id"), "bundle.instrument_id")
        qualified.append(f"{exchange}.{instrument}")
    primary_exchange = _text(primary[0].get("exchange_id"), "bundle.exchange_id")
    primary_instrument = _text(primary[0].get("instrument_id"), "bundle.instrument_id")
    return {
        "instrument": f"{primary_exchange}.{primary_instrument}",
        "authorized_instruments": sorted(qualified),
        "connection_generation": snapshot["connection_generation"],
        "account_fingerprint": snapshot["account_fingerprint"],
        "trading_day": snapshot["trading_day"],
        "exchange_id": primary_exchange,
    }


def _quote_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimNowLiveRunnerBlocked(f"{name}_INVALID")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise SimNowLiveRunnerBlocked(f"{name}_INVALID")
    return value


def _quote_timestamp(value: Any, name: str) -> tuple[str, Any]:
    if isinstance(value, bool) or value in (None, ""):
        raise SimNowLiveRunnerBlocked(f"{name}_MISSING")
    if isinstance(value, (int, float)):
        number = _quote_number(value, name)
        return "number", number
    if isinstance(value, str) and value.strip():
        return "text", value.strip()
    raise SimNowLiveRunnerBlocked(f"{name}_INVALID")


def _reference_quotes(
    snapshot: Mapping[str, Any],
    expected_legs: tuple[tuple[str, str, bool], ...],
    *,
    max_quote_age_seconds: float,
) -> dict[str, Any]:
    if max_quote_age_seconds <= 0 or max_quote_age_seconds > 10:
        raise SimNowLiveRunnerBlocked("REFERENCE_MAX_AGE_INVALID")
    actual_legs = snapshot.get("legs")
    if not isinstance(actual_legs, list) or len(actual_legs) != len(expected_legs):
        raise SimNowLiveRunnerBlocked("REFERENCE_LEGS_TIMING_INCOMPLETE")
    by_symbol = {}
    windows = []
    for exchange, instrument, _primary in expected_legs:
        symbol = f"{exchange}.{instrument}"
        leg = next(
            (
                item
                for item in actual_legs
                if item.get("exchange_id") == exchange and item.get("instrument_id") == instrument
            ),
            None,
        )
        if not isinstance(leg, Mapping):
            raise SimNowLiveRunnerBlocked("REFERENCE_LEGS_SCOPE_MISMATCH")
        requested_monotonic = _quote_number(
            leg.get("requested_monotonic"), f"{symbol}.requested_monotonic"
        )
        received_monotonic = _quote_number(
            leg.get("received_monotonic"), f"{symbol}.received_monotonic"
        )
        if requested_monotonic > received_monotonic:
            raise SimNowLiveRunnerBlocked("REFERENCE_MONOTONIC_ORDER_INVALID")
        try:
            requested_at = datetime.fromisoformat(
                str(leg.get("requested_at_utc")).replace("Z", "+00:00")
            )
            received_at = datetime.fromisoformat(
                str(leg.get("received_at_utc")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise SimNowLiveRunnerBlocked("REFERENCE_UTC_TIMESTAMP_INVALID") from exc
        if requested_at.tzinfo is None or received_at.tzinfo is None or requested_at > received_at:
            raise SimNowLiveRunnerBlocked("REFERENCE_UTC_ORDER_INVALID")
        ask = _quote_number(leg.get("ask_price"), f"{symbol}.ask_price")
        bid = _quote_number(leg.get("bid_price"), f"{symbol}.bid_price")
        ask_quantity = _quote_number(leg.get("ask_volume"), f"{symbol}.ask_volume")
        bid_quantity = _quote_number(leg.get("bid_volume"), f"{symbol}.bid_volume")
        entry_price = _quote_number(leg.get("entry_buy_price"), f"{symbol}.entry_buy_price")
        exit_price = _quote_number(leg.get("exit_sell_price"), f"{symbol}.exit_sell_price")
        if entry_price != ask or exit_price != bid:
            raise SimNowLiveRunnerBlocked("REFERENCE_ENTRY_EXIT_PRICE_MISMATCH")
        if bid > ask:
            raise SimNowLiveRunnerBlocked("REFERENCE_QUOTES_CROSSED")
        windows.append((requested_monotonic, received_monotonic))
        by_symbol[symbol] = {
            "timestamp_kind": "monotonic",
            "timestamp": received_monotonic,
            "ask": ask,
            "bid": bid,
            "ask_quantity": ask_quantity,
            "bid_quantity": bid_quantity,
            "requested_monotonic": requested_monotonic,
            "received_monotonic": received_monotonic,
        }
    now = time.monotonic()
    if max(received for _requested, received in windows) > now + 1e-6:
        raise SimNowLiveRunnerBlocked("REFERENCE_RECEIVED_TIME_IN_FUTURE")
    if now - min(received for _requested, received in windows) > max_quote_age_seconds:
        raise SimNowLiveRunnerBlocked("REFERENCE_QUOTES_STALE")
    if (
        max(received for _requested, received in windows)
        - min(requested for requested, _received in windows)
        > max_quote_age_seconds
    ):
        raise SimNowLiveRunnerBlocked("REFERENCE_ACQUISITION_WINDOW_TOO_WIDE")
    return by_symbol


def _execution_reference(
    snapshot: Any,
    expected_legs: tuple[tuple[str, str, bool], ...],
    *,
    max_quote_age_seconds: float,
    kind: str = "full",
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_SCHEMA_INVALID")
    if snapshot.get("evidence_complete") is not True or snapshot.get("read_only") is not True:
        raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_NOT_SAFE_OR_COMPLETE")
    expected_schema = (
        "backtrader.ctp.bundle-execution-reference.v1"
        if kind == "full"
        else "backtrader.ctp.bundle-quote-reference.v1"
    )
    if snapshot.get("schema_version") != expected_schema:
        raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_SCHEMA_INVALID")
    if kind == "full":
        bundle_preflight = snapshot.get("bundle_preflight")
        if not isinstance(bundle_preflight, Mapping):
            raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_SCOPE_MISSING")
        normalized_bundle = _strict_snapshot(
            bundle_preflight, "EXECUTION_REFERENCE_BUNDLE_PREFLIGHT"
        )
    else:
        # Store quote-only references carry the complete preflight alongside a
        # compact bundle_scope.  The compact summary is never itself a proof.
        bundle_preflight = snapshot.get("bundle_preflight")
        if not isinstance(bundle_preflight, Mapping):
            raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_BUNDLE_PREFLIGHT_MISSING")
        normalized_bundle = _strict_snapshot(bundle_preflight, "QUOTE_REFERENCE_BUNDLE_PREFLIGHT")
        bundle_scope = snapshot.get("bundle_scope")
        if not isinstance(bundle_scope, Mapping):
            raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_SCOPE_MISSING")
        expected_scope = _bundle_scope_summary(normalized_bundle)
        if set(bundle_scope) != set(expected_scope) or any(
            bundle_scope.get(key) != value for key, value in expected_scope.items()
        ):
            raise SimNowLiveRunnerBlocked("QUOTE_REFERENCE_SCOPE_MISMATCH")
    actual_legs = _bundle_leg_identities(normalized_bundle)
    if actual_legs != expected_legs:
        raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_LEGS_MISMATCH")
    normalized = dict(snapshot)
    normalized.update(
        {
            "account_fingerprint": normalized_bundle["account_fingerprint"],
            "trading_day": normalized_bundle["trading_day"],
            "connection_generation": normalized_bundle["connection_generation"],
            "read_only_safe": normalized_bundle["read_only_safe"],
            "_identity_sha256": _identity_hash(normalized_bundle),
            "_legs_sha256": _legs_hash(expected_legs),
            "_reference_scope": normalized_bundle,
        }
    )
    if (
        snapshot.get("write_request_free") is not True
        or normalized_bundle["read_only_safe"] is not True
    ):
        raise SimNowLiveRunnerBlocked("EXECUTION_REFERENCE_NOT_SAFE_OR_COMPLETE")
    _reference_quotes(normalized, expected_legs, max_quote_age_seconds=max_quote_age_seconds)
    return normalized


def _normalized_reconciliation_rounds(
    broker: Any, raw_rounds: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw_rounds, (list, tuple)) or len(raw_rounds) != 2:
        raise SimNowLiveRunnerBlocked("TWO_RAW_RECONCILIATION_ROUNDS_REQUIRED")
    record = getattr(broker, "record_ctp_reconciliation", None)
    state_getter = getattr(broker, "get_ctp_reconciliation_state", None)
    if not callable(record) or not callable(state_getter):
        raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_CAPABILITY_MISSING")
    states = []
    raw_identities = []
    for raw in raw_rounds:
        if not isinstance(raw, Mapping):
            raise SimNowLiveRunnerBlocked("RAW_RECONCILIATION_SCHEMA_INVALID")
        try:
            raw_identities.append(_identity(raw, "raw_reconciliation"))
        except MechanicalCycleBlocked as exc:
            raise SimNowLiveRunnerBlocked(str(exc)) from exc
        try:
            record(dict(raw))
            state = state_getter()
        except Exception as exc:
            raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_FAILED") from exc
        if not isinstance(state, Mapping):
            raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_STATE_INVALID")
        if (
            state.get("account_fingerprint") != raw_identities[-1][0]
            or type(state.get("connection_generation")) is not int
            or state.get("connection_generation") != raw_identities[-1][2]
        ):
            raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_IDENTITY_CHANGED")
        states.append(dict(state))
    final = states[-1]
    if final.get("complete") is not True or final.get("consecutive_complete_rounds", 0) < 2:
        raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_NOT_PASS")
    for state in states:
        if state.get("account_fingerprint") in (None, "") or not isinstance(
            state.get("connection_generation"), int
        ):
            raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_IDENTITY_INCOMPLETE")
        if state.get("unknown_intent_count") != 0 or state.get("unmatched_trade_count") != 0:
            raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_NOT_CLEAR")
    if raw_identities[0] != raw_identities[1]:
        raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_IDENTITY_CHANGED")
    if states[0].get("reconciliation_fingerprint") != states[1].get("reconciliation_fingerprint"):
        raise SimNowLiveRunnerBlocked("BROKER_RECONCILIATION_FINGERPRINT_CHANGED")
    identity = {
        "account_fingerprint": final["account_fingerprint"],
        "trading_day": raw_identities[-1][1],
        "connection_generation": final["connection_generation"],
    }
    normalized = {
        "schema_version": "backtrader.ctp.preflight.v1",
        **identity,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "reconciled": True,
        "broker_reconciliation_state_hash": _hash(final),
        "nonzero_positions": [],
        "active_orders": [],
    }
    return dict(normalized), dict(normalized)


@dataclass
class SimNowMechanicalSession:
    """Caller-owned callback handle; no client or background worker is created."""

    runner: "SimNowLiveRunner"
    cycle: MechanicalCycle
    bundle: ThreeLegBundle
    report: dict[str, Any]

    def submit_next_entry(self) -> Any:
        return self.cycle.submit_next_entry()

    def on_order_update(self, order: Any) -> dict[str, Any]:
        self.cycle.on_order_update(order)
        if self.cycle.phase == "OPEN" and self.cycle.pending_order is None:
            if len(self.cycle.completed_legs) < len(self.cycle.planned_legs):
                self.cycle.submit_next_entry()
        elif self.cycle.phase == "CLOSE" and self.cycle.pending_order is None:
            if len(self.cycle.completed_legs) < len(self.cycle.planned_legs):
                self.cycle.submit_next_exit()
        return self.status()

    def plan_exit(
        self,
        prices: Mapping[str, float],
        *,
        intent_id: str,
        reference_snapshot: Mapping[str, Any],
    ) -> None:
        if self.cycle.state != "OPEN":
            raise SimNowLiveRunnerBlocked("EXIT_REQUIRES_ALL_NATIVE_ENTRY_FILLS")
        self.runner._validate_prices(prices, side="exit", reference_snapshot=reference_snapshot)
        legs = [
            MechanicalLeg(
                symbol=leg.symbol,
                side="sell" if leg.side == "buy" else "buy",
                price=float(prices[leg.symbol]),
                data=leg.data,
                position_side=leg.position_side,
            )
            for leg in self.cycle._entry_legs
        ]
        self.cycle.plan_exit(legs, intent_id=intent_id)

    def submit_next_exit(self) -> Any:
        return self.cycle.submit_next_exit()

    def cancel_pending(self) -> Any:
        return self.cycle.cancel_pending()

    def timeout(self) -> None:
        self.cycle.timeout()

    def reconnect(self, generation: int) -> None:
        self.cycle.reconnect(generation)

    def finalize_flat(self, first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalized_reconciliation_rounds(self.runner.broker, [first, second])
        self.cycle.finalize_flat(*normalized)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "status": "MECHANICAL_PASS" if self.cycle.state == "CLOSED_FLAT" else self.cycle.state,
            "iteration_25": "HFT_NOT_ADMITTED",
            "cycle_id_hash": _hash(self.cycle.cycle_id),
            "phase": self.cycle.phase,
            "pending": self.cycle.pending_order is not None,
            "journal": list(self.cycle.journal),
        }


class SimNowLiveRunner:
    """Preflight-first launcher over caller-owned Store/Broker/feeds."""

    def __init__(
        self,
        *,
        store: Any,
        broker: Any,
        feeds: Mapping[str, Any],
        owner: Any,
        instrument_records: Any,
        product_id: str,
        exchange_id: str,
        trading_day: str,
        snapshots: Mapping[str, Any],
        execution_authorization: Mapping[str, Any] | None = None,
        cycle_id: str = "iter23-mechanical-smoke",
        entry_sides: Mapping[str, str] | None = None,
        basket_budget: int = 3,
        max_quote_age_seconds: float = 2.0,
        exact_instrument_ids: Mapping[str, str] | None = None,
    ):
        if not isinstance(feeds, Mapping) or not feeds:
            raise SimNowLiveRunnerBlocked("CALLER_FEEDS_REQUIRED")
        if not callable(getattr(broker, "buy", None)) or not callable(
            getattr(broker, "sell", None)
        ):
            raise SimNowLiveRunnerBlocked("CALLER_BTAPI_BROKER_REQUIRED")
        self.store = store
        self.broker = broker
        self.feeds = dict(feeds)
        self.owner = owner
        self.instrument_records = instrument_records
        self.product_id = _text(product_id, "product_id")
        self.exchange_id = _text(exchange_id, "exchange_id").upper()
        self.trading_day = _text(trading_day, "trading_day")
        self.snapshots = dict(snapshots)
        self.execution_authorization = execution_authorization
        self.cycle_id = _text(cycle_id, "cycle_id")
        self.entry_sides = dict(entry_sides or {})
        self.basket_budget = basket_budget
        if isinstance(max_quote_age_seconds, bool) or not isinstance(
            max_quote_age_seconds, (int, float)
        ):
            raise SimNowLiveRunnerBlocked("REFERENCE_MAX_AGE_INVALID")
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        self.exact_instrument_ids = (
            dict(exact_instrument_ids) if exact_instrument_ids else None
        )
        if self.exact_instrument_ids is not None and set(self.exact_instrument_ids) != {
            "future",
            "call",
            "put",
        }:
            raise SimNowLiveRunnerBlocked("EXACT_BUNDLE_IDS_MUST_BE_COMPLETE")
        self._bundle: ThreeLegBundle | None = None
        self._proof: dict[str, Any] | None = None
        self._public_status: dict[str, Any] = {}
        self._observed_snapshots: dict[str, Any] = {}
        self._execution_reference_data: dict[str, Any] = {}
        self._entry_quote_timestamp: tuple[str, Any] | None = None
        self._frozen_report: dict[str, Any] | None = None

    def _discover_bundle(self) -> ThreeLegBundle:
        exact = self.exact_instrument_ids or {}
        try:
            return select_three_leg_bundle(
                self.instrument_records,
                product_id=self.product_id,
                exchange_id=self.exchange_id,
                trading_day=self.trading_day,
                **(
                    {
                        "future_instrument_id": exact["future"],
                        "call_instrument_id": exact["call"],
                        "put_instrument_id": exact["put"],
                    }
                    if exact
                    else {}
                ),
            )
        except Exception as exc:
            raise SimNowLiveRunnerBlocked("FCP_BUNDLE_DISCOVERY_FAILED") from exc

    def collect_public_evidence(self, *, timeout: float) -> dict[str, Any]:
        """Explicitly collect Store evidence; never called by :meth:`preflight`."""
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise SimNowLiveRunnerBlocked("PUBLIC_COLLECTION_TIMEOUT_MUST_BE_NONZERO")
        bundle = self._discover_bundle()
        legs = [
            {
                "exchange_id": leg.exchange_id,
                "instrument_id": leg.instrument_id,
                "is_primary": i == 0,
            }
            for i, leg in enumerate((bundle.future, bundle.call, bundle.put))
        ]

        def read(name: str, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
            method = getattr(self.store, name, None)
            if not callable(method):
                raise SimNowLiveRunnerBlocked(f"PUBLIC_CAPABILITY_MISSING:{name}")
            try:
                value = method(*args, **kwargs)
            except Exception as exc:
                raise SimNowLiveRunnerBlocked(f"PUBLIC_READ_FAILED:{name}") from exc
            if not isinstance(value, Mapping):
                raise SimNowLiveRunnerBlocked(f"PUBLIC_READ_SCHEMA_INVALID:{name}")
            return value

        stage_a = read(
            "get_ctp_preflight_snapshot",
            product_id=self.product_id,
            exchange_id=self.exchange_id,
            timeout=float(timeout),
            read_only=True,
        )
        stage_b = read(
            "get_ctp_preflight_snapshot",
            f"{bundle.exchange_id}.{bundle.future.instrument_id}",
            exchange_id=bundle.exchange_id,
            timeout=float(timeout),
            read_only=True,
        )
        reference_method = "get_ctp_bundle_execution_reference_snapshot"
        execution_reference = read(
            reference_method,
            legs,
            timeout=float(timeout),
        )
        collected = {
            "stage_a": stage_a,
            "stage_b": stage_b,
            "bundle_execution_reference": execution_reference,
            "public_capabilities": {reference_method: True},
        }
        return collected

    def _validate_prices(
        self,
        prices: Mapping[str, float],
        *,
        side: str,
        reference_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        if self._bundle is None or not isinstance(prices, Mapping) or side not in {"entry", "exit"}:
            raise SimNowLiveRunnerBlocked("PRICE_REFERENCE_REQUIRED")
        if side == "exit" and reference_snapshot is None:
            raise SimNowLiveRunnerBlocked("EXIT_QUOTE_REFERENCE_REQUIRED")
        reference_snapshot = reference_snapshot or self._execution_reference_data
        expected_legs = tuple(
            (leg.exchange_id, leg.instrument_id, i == 0)
            for i, leg in enumerate((self._bundle.future, self._bundle.call, self._bundle.put))
        )
        validated_reference = _execution_reference(
            reference_snapshot,
            expected_legs,
            max_quote_age_seconds=self.max_quote_age_seconds,
            kind="full" if side == "entry" else "quote",
        )
        quotes = _reference_quotes(
            validated_reference,
            expected_legs,
            max_quote_age_seconds=self.max_quote_age_seconds,
        )
        expected = tuple(
            f"{leg.exchange_id}.{leg.instrument_id}"
            for leg in (self._bundle.future, self._bundle.call, self._bundle.put)
        )
        if set(prices) != set(expected):
            raise SimNowLiveRunnerBlocked("PRICE_LEGS_MUST_MATCH_REFERENCE")
        if side == "exit":
            entry_timestamp = self._entry_quote_timestamp
            exit_quote = next(iter(quotes.values()))
            exit_timestamp = (exit_quote["timestamp_kind"], exit_quote["timestamp"])
            if (
                entry_timestamp is None
                or exit_timestamp[0] != entry_timestamp[0]
                or exit_timestamp[1] <= entry_timestamp[1]
            ):
                raise SimNowLiveRunnerBlocked("EXIT_REFERENCE_MUST_BE_NEWER")
        for symbol in expected:
            value = prices[symbol]
            value = _quote_number(value, f"{symbol}.price")
            quote = quotes[symbol]
            required_price = quote["ask"] if side == "entry" else quote["bid"]
            if value != required_price:
                raise SimNowLiveRunnerBlocked(
                    "ENTRY_PRICE_MUST_EQUAL_REFERENCE_ASK"
                    if side == "entry"
                    else "EXIT_PRICE_MUST_EQUAL_REFERENCE_BID"
                )
            metadata = next(
                leg
                for leg in (self._bundle.future, self._bundle.call, self._bundle.put)
                if f"{leg.exchange_id}.{leg.instrument_id}" == symbol
            )
            try:
                tick = _quote_number(float(metadata.tick_size), "REFERENCE_PRICE_TICK")
            except (TypeError, ValueError):
                raise SimNowLiveRunnerBlocked("REFERENCE_PRICE_TICK_INVALID") from None
            lattice = value / tick
            if not math.isclose(lattice, round(lattice), rel_tol=0.0, abs_tol=1e-9):
                raise SimNowLiveRunnerBlocked("PRICE_NOT_ON_TICK_LATTICE")
        if side == "entry":
            quote = next(iter(quotes.values()))
            self._entry_quote_timestamp = (quote["timestamp_kind"], quote["timestamp"])

    def preflight(self) -> dict[str, Any]:
        if self._frozen_report is not None:
            return dict(self._frozen_report)
        bundle = self._discover_bundle()
        stage_a = _strict_stage(self.snapshots.get("stage_a"), "STAGE_A")
        stage_b = _strict_stage(self.snapshots.get("stage_b"), "STAGE_B")
        expected_legs = tuple(
            (leg.exchange_id, leg.instrument_id, i == 0)
            for i, leg in enumerate((bundle.future, bundle.call, bundle.put))
        )
        execution_reference = _execution_reference(
            self.snapshots.get("bundle_execution_reference"),
            expected_legs,
            max_quote_age_seconds=self.max_quote_age_seconds,
        )
        capabilities = self.snapshots.get("public_capabilities")
        if (
            not isinstance(capabilities, Mapping)
            or capabilities.get("get_ctp_bundle_execution_reference_snapshot") is not True
        ):
            raise SimNowLiveRunnerBlocked(
                "PUBLIC_CAPABILITY_MISSING:get_ctp_bundle_execution_reference_snapshot"
            )
        if _scope_value(stage_a, "exchange_id", "ExchangeID") != self.exchange_id:
            raise SimNowLiveRunnerBlocked("STAGE_A_SCOPE_MISMATCH")
        if _scope_value(stage_a, "product_id", "ProductID") != self.product_id:
            raise SimNowLiveRunnerBlocked("STAGE_A_SCOPE_MISMATCH")
        if _scope_value(stage_b, "exchange_id", "ExchangeID") != bundle.exchange_id:
            raise SimNowLiveRunnerBlocked("STAGE_B_SCOPE_MISMATCH")
        if _scope_value(stage_b, "instrument_id", "InstrumentID") != bundle.future.instrument_id:
            raise SimNowLiveRunnerBlocked("STAGE_B_SCOPE_MISMATCH")
        if _identity(stage_a) != _identity(stage_b) or _identity(stage_a) != _identity(
            execution_reference
        ):
            raise SimNowLiveRunnerBlocked("STAGE_BUNDLE_IDENTITY_MISMATCH")
        if self.basket_budget < 3:
            raise SimNowLiveRunnerBlocked("THREE_LEG_BUDGET_REQUIRED")
        context = self.snapshots.get("preflight_context")
        if (
            not isinstance(context, Mapping)
            or context.get("market_data_only") is not True
            or context.get("execution_armed") is not False
        ):
            raise SimNowLiveRunnerBlocked("PREFLIGHT_MUST_BE_MARKET_DATA_ONLY_UNARMED")
        first, second = _normalized_reconciliation_rounds(
            self.broker, self.snapshots.get("raw_reconciliation_rounds")
        )
        if _identity(first) != _identity(stage_a) or _identity(second) != _identity(stage_a):
            raise SimNowLiveRunnerBlocked("RECONCILIATION_IDENTITY_MISMATCH")
        derived_bundle = {
            "schema_version": "backtrader.ctp.bundle-preflight.v2",
            **{
                key: execution_reference[key]
                for key in ("account_fingerprint", "trading_day", "connection_generation")
            },
            "evidence_complete": True,
            "read_only_safe": True,
            "write_request_free": True,
            "flat": True,
            "active_order_count": 0,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
            "legs": execution_reference["_reference_scope"]["legs"],
            "reconciled": True,
            "snapshot_sha256": execution_reference.get("snapshot_sha256")
            or _hash(execution_reference),
        }
        self._bundle = bundle
        self._execution_reference_data = execution_reference
        self._entry_quote_timestamp = None
        self._proof = {
            "settlement_verified": self.snapshots.get("settlement_verified") is True,
            "bundle_preflight": derived_bundle,
            "reconciliation_rounds": [first, second],
            "reconciliation_semantic_hashes": [_semantic_hash(first), _semantic_hash(second)],
        }
        # Read-only smoke keeps reporting an unconfirmed settlement; the
        # fail-closed boundary stays in MechanicalCycle.arm, which refuses to
        # arm unless settlement_verified is True.
        report = {
            "status": "PREFLIGHT_PASS",
            "execution_admitted": False,
            "iteration_25": "HFT_NOT_ADMITTED",
            "settlement_verified": self._proof["settlement_verified"],
            "bundle": bundle.to_dict(),
            "public_evidence": {
                "stage_a": _redact_snapshot(stage_a, "stage_a"),
                "stage_b": _redact_snapshot(stage_b, "stage_b"),
                "bundle_execution_reference": _redact_snapshot(
                    execution_reference, "execution_reference"
                ),
                "reconciliation_rounds": [
                    _redact_snapshot(first, "reconciliation"),
                    _redact_snapshot(second, "reconciliation"),
                ],
            },
        }
        self._frozen_report = dict(report)
        return dict(report)

    def execute_preflighted(
        self,
        *,
        prices: Mapping[str, float],
        execution_state: Mapping[str, Any],
        reference_snapshot: Mapping[str, Any] | None = None,
        execution_authorization: Mapping[str, Any] | None = None,
        budget_capability: Any = None,
    ) -> SimNowMechanicalSession:
        if self._proof is None or self._frozen_report is None or self._bundle is None:
            raise SimNowLiveRunnerBlocked("PREFLIGHT_REQUIRED_BEFORE_EXECUTION")
        if not isinstance(execution_state, Mapping):
            raise SimNowLiveRunnerBlocked("EXECUTION_LIFECYCLE_PROOF_REQUIRED")
        if execution_state.get("store_armed") is not True:
            raise SimNowLiveRunnerBlocked("STORE_ARM_PROOF_REQUIRED")
        if execution_state.get("broker_started") is not True:
            raise SimNowLiveRunnerBlocked("BROKER_START_PROOF_REQUIRED")
        expected_identity = _identity(self._proof["bundle_preflight"], "frozen_proof")
        try:
            actual_identity = _identity(execution_state, "execution_state")
        except MechanicalCycleBlocked as exc:
            raise SimNowLiveRunnerBlocked(str(exc)) from exc
        if actual_identity != expected_identity:
            raise SimNowLiveRunnerBlocked("EXECUTION_LIFECYCLE_IDENTITY_MISMATCH")
        authorized = _authorization_ready(
            execution_authorization
            if execution_authorization is not None
            else self.execution_authorization
        )
        if authorized["account_fingerprint"] != expected_identity[0]:
            raise SimNowLiveRunnerBlocked("AUTHORIZATION_ACCOUNT_MISMATCH")
        if authorized["connection_generation"] != expected_identity[2]:
            raise SimNowLiveRunnerBlocked("AUTHORIZATION_GENERATION_MISMATCH")
        proof = {
            **self._proof,
            "execution_authorization": {
                **dict(execution_authorization or self.execution_authorization or {}),
                **authorized,
            },
        }
        report = dict(self._frozen_report)
        assert self._bundle is not None and self._proof is not None
        price_map = dict(prices or {})
        self._validate_prices(
            price_map,
            side="entry",
            reference_snapshot=reference_snapshot or self._execution_reference_data,
        )
        legs = (self._bundle.future, self._bundle.call, self._bundle.put)
        mechanical_legs = []
        for leg in legs:
            symbol = f"{leg.exchange_id}.{leg.instrument_id}"
            side = self.entry_sides.get(symbol, self.entry_sides.get(leg.instrument_id, "buy"))
            if side != "buy":
                raise SimNowLiveRunnerBlocked("ENTRY_SIDE_MUST_BE_BUY")
            mechanical_legs.append(
                MechanicalLeg(
                    symbol=symbol,
                    side=side,
                    price=float(price_map[symbol]),
                    data=self.feeds[symbol],
                )
            )
        cycle = MechanicalCycle(
            broker=self.broker,
            owner=self.owner,
            feeds=self.feeds,
            cycle_id=self.cycle_id,
            budget_capability=budget_capability,
        )
        try:
            cycle.arm(proof)
            intent_id = f"{self.cycle_id}:entry"
            cycle.plan_entry(mechanical_legs, intent_id=intent_id)
            session = SimNowMechanicalSession(self, cycle, self._bundle, report)
            session.submit_next_entry()
            return session
        except MechanicalCycleBlocked as exc:
            raise SimNowLiveRunnerBlocked(str(exc)) from exc

    begin = execute_preflighted

    def start(
        self,
        *,
        execute: bool = False,
        prices: Mapping[str, float] | None = None,
        execution_state: Mapping[str, Any] | None = None,
        reference_snapshot: Mapping[str, Any] | None = None,
    ) -> Any:
        if not execute:
            return self.preflight()
        return self.execute_preflighted(
            prices=dict(prices or {}),
            execution_state=execution_state,
            reference_snapshot=reference_snapshot,
        )


def launch_three_leg_smoke(**kwargs: Any) -> Any:
    """Convenience entry point; ``execute`` defaults to the safe read-only path."""
    execute = bool(kwargs.pop("execute", False))
    prices = kwargs.pop("prices", None)
    return SimNowLiveRunner(**kwargs).start(execute=execute, prices=prices)


__all__ = [
    "SimNowLiveRunner",
    "SimNowLiveRunnerBlocked",
    "SimNowMechanicalSession",
    "launch_three_leg_smoke",
]
