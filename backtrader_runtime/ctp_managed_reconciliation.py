"""Pure classification of verified managed CTP order readback.

This module never talks to a provider, submits or cancels an order, or grants a
write capability.  Callers supply the typed results from
``ctp_simulation_execution`` and the application's existing native query
evidence verifier.  A queue receipt, request return code, locally constructed
snapshot, or unverified ``complete=True`` result cannot produce an observed
state here.

The classifier covers the Iteration 41 SimNow sandbox snapshot contracts.  It
does not establish production CTP admission, cross-host account fencing, a
transactionally atomic snapshot across separate CTP queries, or a durable
provider acknowledgement.  The injected verifier must authenticate each
native query result against account, TradingDay, connection generation,
request history, full query completion and callback quiescence.  Missing or
contradictory evidence is represented as ``UNKNOWN``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, Tuple

from .ctp_simulation_execution import (
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationOrderSnapshot,
    CtpSimulationPositionSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationSessionIdentity,
    CtpSimulationTradeSnapshot,
    CtpSimulationWriteRequest,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIDES = frozenset(("BUY", "SELL"))


class CtpManagedOrderState(str, Enum):
    """Order state established by verified native readback."""

    UNKNOWN = "UNKNOWN"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


@dataclass(frozen=True)
class CtpManagedReconciliationObservation:
    """Detached, non-authorizing classification for one runtime order ID.

    ``observed`` means this pure classifier found mutually consistent,
    verifier-approved native query evidence.  It is deliberately not an SDK
    ``ProviderObservation`` and cannot be passed to the managed execution
    journal as a write acknowledgement without a separate reviewed binding.
    """

    runtime_order_id: str
    state: CtpManagedOrderState
    account_fingerprint_sha256: Optional[str] = None
    trading_day: Optional[str] = None
    connection_generation: Optional[int] = None
    traded_quantity: int = 0
    trade_count: int = 0
    reason: str = ""

    @property
    def observed(self) -> bool:
        return self.state is not CtpManagedOrderState.UNKNOWN


class CtpManagedQueryEvidenceVerifier(Protocol):
    """Existing verifier contract; this adapter does not implement one."""

    def verify(
        self,
        query_kind: str,
        result: CtpSimulationQueryResult,
        *,
        expected_identity: CtpSimulationSessionIdentity,
        registration_digest: str,
    ) -> bool:
        ...


def _unknown(runtime_order_id: str, reason: str) -> CtpManagedReconciliationObservation:
    return CtpManagedReconciliationObservation(
        runtime_order_id=runtime_order_id,
        state=CtpManagedOrderState.UNKNOWN,
        reason=reason,
    )


def _position_totals(
    result: CtpSimulationQueryResult,
    *,
    instrument_id: str,
    exchange_id: str,
) -> Optional[dict[str, int]]:
    if type(result) is not CtpSimulationQueryResult:
        return None
    totals = {"BUY": 0, "SELL": 0}
    seen: set[str] = set()
    for record in result.records:
        if (
            type(record) is not CtpSimulationPositionSnapshot
            or record.instrument_id != instrument_id
            or record.exchange_id != exchange_id
            or record.side not in _SIDES
            or type(record.quantity) is not int
            or record.quantity < 0
            or record.side in seen
        ):
            return None
        seen.add(record.side)
        totals[record.side] = record.quantity
    # The CTP adapter normalizes both long and short sides, including zeroes.
    # An omitted side is ambiguous and must not be treated as a zero position.
    if seen != _SIDES:
        return None
    return totals


def _verified(
    result: Any,
    *,
    query_kind: str,
    expected_identity: CtpSimulationSessionIdentity,
    registration_digest: str,
    verifier: CtpManagedQueryEvidenceVerifier,
) -> bool:
    if (
        type(result) is not CtpSimulationQueryResult
        or result.complete is not True
        or type(result.records) is not tuple
        or result.identity != expected_identity
        or result.native_evidence is None
    ):
        return False
    try:
        return (
            verifier.verify(
                query_kind,
                result,
                expected_identity=expected_identity,
                registration_digest=registration_digest,
            )
            is True
        )
    except Exception:
        return False


def observe_ctp_managed_order(
    *,
    runtime_order_id: str,
    request: CtpSimulationWriteRequest,
    expected_identity: CtpSimulationSessionIdentity,
    registration_digest: str,
    baseline_positions: CtpSimulationQueryResult,
    orders: CtpSimulationQueryResult,
    trades: CtpSimulationQueryResult,
    positions: CtpSimulationQueryResult,
    verifier: CtpManagedQueryEvidenceVerifier,
    expected_cancel_action_ids: Tuple[str, ...] = (),
    cancel_requests: Optional[CtpSimulationQueryResult] = None,
) -> CtpManagedReconciliationObservation:
    """Classify one managed CTP order from verified exact query results.

    ``baseline_positions`` is the complete, verified position query captured
    before order submission. ``positions`` is the complete query used for
    reconciliation. When cancellations were journaled, callers must provide
    every expected ``action_id`` and its complete native cancel readback.
    Those snapshots must bind each action to this order's exact CTP target.

    Every query is independently checked through the injected verifier. This
    cannot provide transaction-level atomicity across CTP queries; a verifier
    or caller that cannot establish stable session identity, coverage and
    callback quiescence must reject. The function never trusts native insert
    or cancel request return codes.
    """

    safe_id = runtime_order_id if type(runtime_order_id) is str else ""
    if (
        not safe_id
        or type(request) is not CtpSimulationWriteRequest
        or request.action != "SUBMIT"
        or request.client_order_id != safe_id
    ):
        return _unknown(safe_id, "runtime_order_request_mismatch")
    if (
        type(expected_identity) is not CtpSimulationSessionIdentity
        or type(registration_digest) is not str
        or not _SHA256_RE.fullmatch(registration_digest)
        or not callable(getattr(verifier, "verify", None))
    ):
        return _unknown(safe_id, "reconciliation_binding_invalid")
    if (
        type(expected_cancel_action_ids) is not tuple
        or any(type(action_id) is not str or not action_id for action_id in expected_cancel_action_ids)
        or len(set(expected_cancel_action_ids)) != len(expected_cancel_action_ids)
    ):
        return _unknown(safe_id, "cancel_action_scope_invalid")
    if bool(expected_cancel_action_ids) != (cancel_requests is not None):
        return _unknown(safe_id, "cancel_readback_missing_or_unexpected")

    required = (
        ("positions", baseline_positions),
        ("orders", orders),
        ("trades", trades),
        ("positions", positions),
    )
    if any(
        not _verified(
            result,
            query_kind=query_kind,
            expected_identity=expected_identity,
            registration_digest=registration_digest,
            verifier=verifier,
        )
        for query_kind, result in required
    ):
        return _unknown(safe_id, "native_query_evidence_incomplete_or_unverified")
    if cancel_requests is not None and not _verified(
        cancel_requests,
        query_kind="cancel_requests",
        expected_identity=expected_identity,
        registration_digest=registration_digest,
        verifier=verifier,
    ):
        return _unknown(safe_id, "native_cancel_evidence_incomplete_or_unverified")

    if len(orders.records) != 1 or type(orders.records[0]) is not CtpSimulationOrderSnapshot:
        return _unknown(safe_id, "native_order_readback_ambiguous")
    order = orders.records[0]
    if (
        order.client_order_id != safe_id
        or order.instrument_id != request.instrument_id
        or order.exchange_id != request.exchange_id
        or order.side != request.side
        or order.quantity != request.quantity
        or order.limit_price != request.limit_price
    ):
        return _unknown(safe_id, "native_order_readback_mismatch")
    coherent_quantity = {
        "OPEN": order.traded_quantity == 0,
        "PARTIAL": 0 < order.traded_quantity < order.quantity,
        "FILLED": order.traded_quantity == order.quantity,
        "REJECTED": order.traded_quantity == 0,
        "CANCELED": order.traded_quantity < order.quantity,
    }
    if order.status not in coherent_quantity or not coherent_quantity[order.status]:
        return _unknown(safe_id, "native_order_status_quantity_mismatch")

    if any(type(record) is not CtpSimulationTradeSnapshot for record in trades.records):
        return _unknown(safe_id, "native_trade_readback_invalid")
    trade_ids = [record.trade_id for record in trades.records]
    if len(set(trade_ids)) != len(trade_ids) or any(
        record.client_order_id != safe_id
        or record.instrument_id != request.instrument_id
        or record.exchange_id != request.exchange_id
        or record.side != request.side
        for record in trades.records
    ):
        return _unknown(safe_id, "native_trade_readback_mismatch_or_duplicate")
    trade_quantity = sum(record.quantity for record in trades.records)
    if trade_quantity != order.traded_quantity:
        return _unknown(safe_id, "native_trade_volume_mismatch")

    before = _position_totals(
        baseline_positions,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
    )
    after = _position_totals(
        positions,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
    )
    if before is None or after is None:
        return _unknown(safe_id, "native_position_readback_incomplete_or_mismatched")
    expected_after = dict(before)
    expected_after[request.side] += order.traded_quantity
    if after != expected_after:
        return _unknown(safe_id, "native_position_delta_mismatch")

    if cancel_requests is not None:
        records = cancel_requests.records
        if (
            len(records) != len(expected_cancel_action_ids)
            or any(type(record) is not CtpSimulationCancelRequestSnapshot for record in records)
        ):
            return _unknown(safe_id, "native_cancel_readback_ambiguous")
        by_id = {record.action_id: record for record in records}
        if len(by_id) != len(records) or set(by_id) != set(expected_cancel_action_ids):
            return _unknown(safe_id, "native_cancel_action_set_mismatch")
        canceled = False
        for action_id in expected_cancel_action_ids:
            record = by_id[action_id]
            if (
                record.client_order_id != safe_id
                or record.target_order_sys_id != order.order_sys_id
                or record.target_order_ref != order.order_ref
                or record.target_front_id != order.front_id
                or record.target_session_id != order.session_id
                or record.status not in ("CANCELED", "REJECTED")
            ):
                return _unknown(safe_id, "native_cancel_target_or_outcome_mismatch")
            canceled = canceled or record.status == "CANCELED"
        if (order.status == "CANCELED") != canceled:
            return _unknown(safe_id, "native_cancel_order_state_mismatch")

    state = {
        "OPEN": CtpManagedOrderState.ACCEPTED,
        "PARTIAL": CtpManagedOrderState.PARTIALLY_FILLED,
        "FILLED": CtpManagedOrderState.FILLED,
        "REJECTED": CtpManagedOrderState.REJECTED,
        "CANCELED": CtpManagedOrderState.CANCELED,
    }[order.status]
    return CtpManagedReconciliationObservation(
        runtime_order_id=safe_id,
        state=state,
        account_fingerprint_sha256=expected_identity.account_fingerprint_sha256,
        trading_day=expected_identity.trading_day,
        connection_generation=expected_identity.connection_generation,
        traded_quantity=order.traded_quantity,
        trade_count=len(trades.records),
        reason="verified_native_readback",
    )


__all__ = [
    "CtpManagedOrderState",
    "CtpManagedQueryEvidenceVerifier",
    "CtpManagedReconciliationObservation",
    "observe_ctp_managed_order",
]
