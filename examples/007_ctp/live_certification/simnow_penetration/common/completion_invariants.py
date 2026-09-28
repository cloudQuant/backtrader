"""Pure-data lifecycle and account reconciliation invariants for 007 cases.

This checker is unregistered. It performs no provider I/O and trusts no local
result summary. Callers supply normalized managed-request receipts, native
order/trade callbacks, and complete before/after order/position/account query
snapshots. It validates shape and cross-source correlations only: source
authenticity, real-account ownership, provider semantics, and certification
still require independent review. Its strongest result is REVIEW_REQUIRED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from typing import Any, Mapping

from .case_engine import (
    CertificationEvidence,
    CertificationEvidenceTracker,
    EvidenceContractError,
    IssuedRequestReceipt,
    validate_issued_request_receipt,
)
from .certification import (
    RECONCILIATION_EXPECTATIONS,
    SCENARIOS_BY_CASE_ID,
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CompletionEvidenceError(ValueError):
    """Raised when a supplied evidence row is malformed or untyped."""


class CompletionStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    EXTERNAL_CONDITION_UNAVAILABLE = "EXTERNAL_CONDITION_UNAVAILABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class RequestAction(str, Enum):
    SUBMIT = "submit"
    CANCEL = "cancel"
    BATCH_CANCEL = "batch_cancel"


class DispatchState(str, Enum):
    DISPATCHED = "dispatched"
    BLOCKED_PRE_DISPATCH = "blocked_pre_dispatch"


class NativeOrderFactKind(str, Enum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    CANCELED = "canceled"
    FILLED = "filled"
    REJECTED = "rejected"


class SnapshotPhase(str, Enum):
    BASELINE = "baseline"
    FINAL = "final"


@dataclass(frozen=True)
class CloseablePositionBucket:
    """Provider position-query bucket keyed by instrument, held side, and close offset."""

    instrument_id: str
    position_side: str  # long / short
    offset: str  # close_today / close_yesterday
    quantity: Decimal | str | int | float


@dataclass(frozen=True)
class ManagedOrderRequest:
    """Managed runtime receipt for a submit/cancel attempt, not a write grant."""

    request_id: str
    action: RequestAction
    dispatch_state: DispatchState
    order_refs: tuple[str, ...]
    occurred_at_utc: str
    sequence: int
    evidence_sha256: str
    source: str = "managed_runtime_receipt"
    quantity: Decimal | str | int | float | None = None
    instrument_id: str | None = None
    direction: str | None = None
    offset: str | None = None
    account_id_masked: str | None = None
    provider_session_id: str | None = None
    request_generation: int | None = None
    intent_key: str | None = None
    trading_day: str | None = None


@dataclass(frozen=True)
class NativeOrderFact:
    event_id: str
    fact: NativeOrderFactKind
    callback_name: str
    source: str
    order_ref: str
    external_order_id: str
    instrument_id: str
    status: str
    traded_quantity: Decimal | str | int | float
    remaining_quantity: Decimal | str | int | float
    session_id: str
    trading_day: str
    source_sequence: int
    occurred_at_utc: str
    evidence_sha256: str
    error_id: int = 0
    direction: str | None = None
    offset: str | None = None
    account_id_masked: str | None = None


@dataclass(frozen=True)
class NativeTradeFact:
    event_id: str
    trade_id: str
    order_ref: str
    instrument_id: str
    quantity: Decimal | str | int | float
    direction: str
    price: Decimal | str | int | float
    callback_name: str
    source: str
    session_id: str
    trading_day: str
    source_sequence: int
    occurred_at_utc: str
    evidence_sha256: str
    external_order_id: str = ""
    offset: str | None = None
    account_id_masked: str | None = None


@dataclass(frozen=True)
class AccountReconciliationSnapshot:
    """Three completed native queries; positions are signed net by instrument.

    ``order_query_id``/``position_query_id``/``account_query_id`` and the
    optional ``query_round_id`` are local query-coordinator correlations, not
    provider-issued query IDs. The corresponding ``query_native_request_ids``
    map contains CTP's echoed callback ``nRequestID`` values. Query sequences
    and ``occurred_at_utc`` are local SDK callback-arrival metadata; they are
    not provider timestamps or provider sequence numbers. This checker cannot
    independently prove that a future adapter supplies a truthful timeline.
    """

    phase: SnapshotPhase
    session_id: str
    trading_day: str
    occurred_at_utc: str
    order_query_id: str
    position_query_id: str
    account_query_id: str
    order_query_sequence: int
    position_query_sequence: int
    account_query_sequence: int
    open_order_refs: tuple[str, ...]
    positions: Mapping[str, Decimal | str | int | float]
    funds: Mapping[str, Decimal | str | int | float]
    callback_names: tuple[str, ...]
    source: str
    evidence_sha256: str
    query_error_ids: Mapping[str, int] = field(default_factory=dict)
    query_is_last: Mapping[str, bool] = field(default_factory=dict)
    closeable_quantities: Mapping[str, Decimal | str | int | float] = field(default_factory=dict)
    closeable_position_buckets: tuple[CloseablePositionBucket, ...] = ()
    account_id_masked: str | None = None
    client_instance_id: str = ""
    arrival_generation: int = 0
    query_native_request_ids: Mapping[str, int] = field(default_factory=dict)
    query_round_id: str = ""
    query_id_origin: str = ""
    query_round_id_origin: str = ""
    sequence_origin: str = ""
    timestamp_origin: str = ""
    query_issued_request_receipts: Mapping[str, IssuedRequestReceipt] = field(default_factory=dict)
    query_request_generations: Mapping[str, int] = field(default_factory=dict)
    query_arrival_times_utc: Mapping[str, str] = field(default_factory=dict)
    query_arrival_monotonic: Mapping[str, float] = field(default_factory=dict)
    session_identity_origin: str = ""


@dataclass(frozen=True)
class ExternalDependency:
    dependency_id: str
    state: str
    evidence_ref: str
    reason: str = ""
    source: str = "control_plane_receipt"
    evidence_sha256: str = ""
    fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionEvidence:
    case_id: str
    scenario_evidence: tuple[CertificationEvidence, ...] = ()
    managed_requests: tuple[ManagedOrderRequest, ...] = ()
    order_facts: tuple[NativeOrderFact, ...] = ()
    trade_facts: tuple[NativeTradeFact, ...] = ()
    snapshots: tuple[AccountReconciliationSnapshot, ...] = ()
    external_dependencies: tuple[ExternalDependency, ...] = ()


@dataclass(frozen=True)
class CompletionReport:
    case_id: str
    scenario_id: str
    status: CompletionStatus
    certification_pass: bool
    dispatch_permitted: bool
    source_authenticity_verified: bool
    missing_invariants: tuple[str, ...]
    contradictions: tuple[str, ...]
    unavailable_dependencies: tuple[str, ...]
    review_reasons: tuple[str, ...]


_CALLBACK_BY_FACT = {
    NativeOrderFactKind.ACCEPTED: "OnRtnOrder",
    NativeOrderFactKind.PARTIAL: "OnRtnOrder",
    NativeOrderFactKind.CANCELED: "OnRtnOrder",
    NativeOrderFactKind.FILLED: "OnRtnOrder",
    NativeOrderFactKind.REJECTED: "OnRspOrderInsert",
}
_STATUS_BY_FACT = {
    NativeOrderFactKind.ACCEPTED: {"accepted", "working"},
    NativeOrderFactKind.PARTIAL: {"partial"},
    NativeOrderFactKind.CANCELED: {"canceled", "cancelled"},
    NativeOrderFactKind.FILLED: {"filled"},
    NativeOrderFactKind.REJECTED: {"rejected"},
}
_TERMINAL_FACTS = {
    NativeOrderFactKind.CANCELED,
    NativeOrderFactKind.FILLED,
    NativeOrderFactKind.REJECTED,
}
_REQUIRED_QUERY_CALLBACKS = {
    "OnRspQryOrder",
    "OnRspQryInvestorPosition",
    "OnRspQryTradingAccount",
}
_REQUIRED_FUND_FIELDS = {"cash", "available_funds", "equity"}
_EXPECTED_REMOTE_REJECTION_CASES = frozenset({"E01", "E02", "E03", "EM01"})
_REQUIRED_DEPENDENCIES = {
    "M02": {"external_disconnect"},
    "M03": {"external_reconnect"},
    "E01": {"insufficient_funds"},
    "E02": {"insufficient_position"},
    "E03": {"market_state"},
    "EM01": {"account_permission_disabled", "account_permission_restored"},
    "EM02": {"strategy_pause_authorized"},
    "EM03": {"gateway_force_logout_ack"},
}


def evaluate_case_completion(evidence: CompletionEvidence) -> CompletionReport:
    """Check order terminality, trade conservation, account delta, and cleanup.

    The result is a reconciliation status only. Even a complete result remains
    REVIEW_REQUIRED with PASS and dispatch authority hard-coded false.
    """

    case_id = evidence.case_id
    scenario = SCENARIOS_BY_CASE_ID.get(case_id)
    expectation = RECONCILIATION_EXPECTATIONS.get(case_id)
    if scenario is None or expectation is None:
        raise CompletionEvidenceError(f"unknown certification case {case_id!r}")
    _validate_rows(evidence)
    unavailable = tuple(
        f"{item.dependency_id}:{item.reason}"
        for item in evidence.external_dependencies
        if item.state == "unavailable"
    )
    missing, contradictions = _derive_invariants(evidence, expectation)
    scenario_missing, scenario_contradictions = _scenario_invariants(evidence)
    missing.extend(scenario_missing)
    contradictions.extend(scenario_contradictions)
    review_reasons = [
        "provider source authenticity and account ownership require independent verification"
    ]
    if evidence.trade_facts:
        review_reasons.append(
            "cash/equity deltas, fees, and margin effects require provider-specific independent accounting review"
        )
    if unavailable:
        status = CompletionStatus.EXTERNAL_CONDITION_UNAVAILABLE
    elif missing or contradictions:
        status = CompletionStatus.INCOMPLETE
    else:
        status = CompletionStatus.REVIEW_REQUIRED
    return CompletionReport(
        case_id=case_id,
        scenario_id=scenario.scenario_id,
        status=status,
        certification_pass=False,
        dispatch_permitted=False,
        source_authenticity_verified=False,
        missing_invariants=tuple(dict.fromkeys(missing)),
        contradictions=tuple(dict.fromkeys(contradictions)),
        unavailable_dependencies=unavailable,
        review_reasons=tuple(review_reasons),
    )


def _scenario_invariants(evidence: CompletionEvidence) -> tuple[list[str], list[str]]:
    """Require the canonical scenario evidence contract for every case."""

    tracker = CertificationEvidenceTracker(evidence.case_id)
    try:
        for row in evidence.scenario_evidence:
            tracker.record(row)
    except EvidenceContractError as exc:
        raise CompletionEvidenceError(str(exc)) from exc
    snapshot = tracker.snapshot()
    missing = [
        *(f"scenario_event:{item}" for item in snapshot["missing_events"]),
        *(f"scenario_field:{item}" for item in snapshot["missing_evidence_fields"]),
        *(f"scenario_provenance_policy:{item}" for item in snapshot["missing_provenance_policies"]),
        *(f"scenario_correlation:{item}" for item in snapshot["missing_event_correlations"]),
    ]
    contradictions: list[str] = []
    _check_scenario_correlations(evidence, contradictions)
    return missing, contradictions


def validation_failure_conditions(
    case_id: str, fields: Mapping[str, Any], occurred_at_utc: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Check pure factual conditions for the V01/V02/V03 local-rejection cases.

    This validates supplied data only. In particular, the authoritative lookup
    flags and metadata digests are not authenticated here, and a complete result
    is still only eligible for REVIEW_REQUIRED.
    """

    if case_id not in {"V01", "V02", "V03"}:
        return (), ()

    missing: list[str] = []
    contradictions: list[str] = []
    if fields.get("dispatch_absent") is not True:
        missing.append("validation_rejection_requires_proven_absent_dispatch")
    reference_digest = fields.get("reference_data_digest")
    if not isinstance(reference_digest, str) or not _SHA256_RE.fullmatch(reference_digest):
        missing.append("validation_requires_reference_data_sha256")

    if case_id == "V01":
        instrument = fields.get("instrument_id")
        if fields.get("instrument") != instrument:
            contradictions.append("validation_instrument_alias_mismatch")
        lookup_result = fields.get("authoritative_lookup_result")
        lookup_instrument = fields.get("authoritative_lookup_instrument")
        lookup_at = _parse_utc(str(fields.get("authoritative_lookup_at_utc", "")))
        required_lookup_fields = (
            fields.get("authoritative_lookup_source"),
            fields.get("authoritative_lookup_id"),
        )
        if not isinstance(instrument, str) or not instrument.strip():
            missing.append("unknown_contract_requires_instrument_id")
        if fields.get("authoritative_lookup_complete") is not True:
            missing.append("unknown_contract_requires_complete_authoritative_lookup")
        if fields.get("authoritative_lookup_authoritative") is not True:
            missing.append("unknown_contract_requires_authoritative_reference_source")
        if any(not isinstance(value, str) or not value.strip() for value in required_lookup_fields):
            missing.append("unknown_contract_requires_lookup_source_and_query_id")
        if lookup_at is None:
            missing.append("unknown_contract_requires_utc_lookup_time")
        if lookup_result != "not_found":
            contradictions.append("authoritative_contract_lookup_did_not_report_not_found")
        if instrument and lookup_instrument != instrument:
            contradictions.append("authoritative_contract_lookup_instrument_mismatch")
        rejection_at = _parse_utc(occurred_at_utc)
        if lookup_at is not None and rejection_at is not None and lookup_at > rejection_at:
            contradictions.append("contract_lookup_must_precede_local_validation_rejection")
    elif case_id == "V02":
        price = _decimal(fields.get("proposed_price"))
        if _decimal(fields.get("price")) != price:
            contradictions.append("validation_price_alias_mismatch")
        price_tick = _decimal(fields.get("price_tick"))
        if price is None or price <= 0:
            missing.append("tick_validation_requires_positive_finite_price")
        if price_tick is None or price_tick <= 0:
            missing.append("tick_validation_requires_positive_finite_tick")
        if price is not None and price_tick is not None and price > 0 and price_tick > 0:
            if not _bounded_contract_decimal(price) or not _bounded_contract_decimal(price_tick):
                missing.append("tick_validation_requires_bounded_contract_decimals")
            elif Fraction(price) % Fraction(price_tick) == 0:
                contradictions.append("reported_price_is_aligned_to_contract_tick")
    else:  # V03
        size = _decimal(fields.get("requested_size"))
        if _decimal(fields.get("size")) != size:
            contradictions.append("validation_size_alias_mismatch")
        maximum = _decimal(fields.get("max_order_size"))
        if size is None or size <= 0:
            missing.append("maximum_size_validation_requires_positive_finite_size")
        elif not _bounded_contract_decimal(size):
            missing.append("maximum_size_validation_requires_bounded_size")
        elif size != size.to_integral_value():
            missing.append("maximum_size_validation_requires_integer_order_size")
        if maximum is None or maximum <= 0:
            missing.append("maximum_size_validation_requires_positive_finite_limit")
        elif not _bounded_contract_decimal(maximum):
            missing.append("maximum_size_validation_requires_bounded_limit")
        elif maximum != maximum.to_integral_value():
            missing.append("maximum_size_validation_requires_integer_limit")
        if (
            size is not None
            and maximum is not None
            and _bounded_contract_decimal(size)
            and _bounded_contract_decimal(maximum)
            and size <= maximum
        ):
            contradictions.append("reported_size_does_not_exceed_contract_maximum")

    return tuple(missing), tuple(contradictions)


def _check_scenario_correlations(evidence: CompletionEvidence, contradictions: list[str]) -> None:
    rows_by_kind: dict[str, list[CertificationEvidence]] = {}
    for row in evidence.scenario_evidence:
        rows_by_kind.setdefault(row.event_kind, []).append(row)
    managed_by_action = {
        action: [request for request in evidence.managed_requests if request.action is action]
        for action in RequestAction
    }
    state_values = {
        DispatchState.DISPATCHED: "dispatched",
        DispatchState.BLOCKED_PRE_DISPATCH: "blocked_pre_dispatch",
    }
    for event_kind, action in (
        ("order_submit_request", RequestAction.SUBMIT),
        ("order_cancel_request", RequestAction.CANCEL),
    ):
        rows = rows_by_kind.get(event_kind, [])
        if not rows:
            continue
        requests = managed_by_action[action]
        row_keys = sorted(
            (str(row.fields.get("order_ref")), str(row.fields.get("dispatch_state")))
            for row in rows
        )
        request_keys = sorted(
            (ref, state_values[request.dispatch_state])
            for request in requests
            for ref in request.order_refs
        )
        if row_keys != request_keys:
            contradictions.append(f"{event_kind}_does_not_match_managed_request_receipts")
    batch_rows = rows_by_kind.get("batch_cancel_requested", [])
    batch_requests = managed_by_action[RequestAction.BATCH_CANCEL]
    if batch_rows and (
        len(batch_rows) != len(batch_requests)
        or any(
            set(row.fields.get("order_refs", ())) != set(request.order_refs)
            or row.fields.get("dispatch_state") != state_values[request.dispatch_state]
            for row, request in zip(batch_rows, batch_requests)
        )
    ):
        contradictions.append("batch_cancel_event_does_not_match_managed_request_receipt")
    for event_kind, fact_kind in (
        ("order_status_accepted", NativeOrderFactKind.ACCEPTED),
        ("order_status_canceled", NativeOrderFactKind.CANCELED),
        ("order_reject_remote", NativeOrderFactKind.REJECTED),
    ):
        rows = rows_by_kind.get(event_kind, [])
        facts = [fact for fact in evidence.order_facts if fact.fact is fact_kind]
        for row in rows:
            matching = [
                fact
                for fact in facts
                if row.fields.get("order_ref") == fact.order_ref
                and row.fields.get("external_order_id", fact.external_order_id)
                == fact.external_order_id
            ]
            if not matching:
                contradictions.append(f"{event_kind}_has_no_matching_native_order_fact")
            elif event_kind == "order_reject_remote" and any(
                row.fields.get("ErrorID") != fact.error_id for fact in matching
            ):
                contradictions.append("remote_rejection_event_error_id_mismatch")
    trade_rows = rows_by_kind.get("trade_execution", [])
    if trade_rows:
        fact_map = {fact.trade_id: fact for fact in evidence.trade_facts}
        for row in trade_rows:
            fact = fact_map.get(str(row.fields.get("trade_id")))
            if (
                fact is None
                or row.fields.get("order_ref") != fact.order_ref
                or row.fields.get("external_order_id") != fact.external_order_id
            ):
                contradictions.append("trade_event_does_not_match_native_trade_fact")
                continue
            if evidence.case_id == "L01" and any(
                key not in row.fields for key in ("instrument_id", "quantity", "direction", "price")
            ):
                contradictions.append("trade_log_requires_complete_native_trade_fields")
            if (
                (
                    "instrument_id" in row.fields
                    and row.fields["instrument_id"] != fact.instrument_id
                )
                or ("direction" in row.fields and row.fields["direction"] != fact.direction)
                or (
                    "quantity" in row.fields
                    and _decimal(row.fields["quantity"]) != _decimal(fact.quantity)
                )
                or ("price" in row.fields and _decimal(row.fields["price"]) != _decimal(fact.price))
            ):
                contradictions.append("trade_event_fields_do_not_match_native_trade_fact")


def _validate_rows(evidence: CompletionEvidence) -> None:
    c01_native_login_present = evidence.case_id == "C01" and any(
        row.event_kind == "store_login_success" for row in evidence.scenario_evidence
    )
    if len({request.request_id for request in evidence.managed_requests}) != len(
        evidence.managed_requests
    ):
        raise CompletionEvidenceError("duplicate managed request_id")
    if len({fact.event_id for fact in evidence.order_facts}) != len(evidence.order_facts):
        raise CompletionEvidenceError("duplicate native order event_id")
    if len({fact.event_id for fact in evidence.trade_facts}) != len(evidence.trade_facts):
        raise CompletionEvidenceError("duplicate native trade event_id")
    if len({fact.trade_id for fact in evidence.trade_facts}) != len(evidence.trade_facts):
        raise CompletionEvidenceError("duplicate native trade_id")

    for request in evidence.managed_requests:
        if request.source != "managed_runtime_receipt":
            raise CompletionEvidenceError("managed intent must use managed runtime receipt source")
        if not request.request_id or not request.order_refs:
            raise CompletionEvidenceError("managed request requires id and order refs")
        if any(not isinstance(ref, str) or not ref for ref in request.order_refs):
            raise CompletionEvidenceError("managed request order refs must be non-empty strings")
        if request.action is RequestAction.SUBMIT and len(request.order_refs) != 1:
            raise CompletionEvidenceError("one submit request must identify exactly one order ref")
        if request.action is RequestAction.BATCH_CANCEL and len(set(request.order_refs)) < 2:
            raise CompletionEvidenceError("batch cancel must identify at least two distinct refs")
        if request.action is RequestAction.SUBMIT:
            quantity = _decimal(request.quantity)
            if quantity is None or quantity <= 0:
                raise CompletionEvidenceError("submit receipt requires positive requested quantity")
        elif request.quantity is not None:
            raise CompletionEvidenceError("only submit receipts may carry requested quantity")
        if len(set(request.order_refs)) != len(request.order_refs):
            raise CompletionEvidenceError("request contains duplicate order refs")
        if not _SHA256_RE.fullmatch(request.evidence_sha256):
            raise CompletionEvidenceError("managed request requires SHA-256 evidence digest")
        if request.sequence < 1 or _parse_utc(request.occurred_at_utc) is None:
            raise CompletionEvidenceError("managed request requires positive sequence and UTC time")
        if request.instrument_id is not None and not request.instrument_id.strip():
            raise CompletionEvidenceError("managed request instrument id must be non-empty")
        if request.direction not in {None, "buy", "sell"}:
            raise CompletionEvidenceError("managed request direction must be buy or sell")
        if request.offset not in {None, "open", "close", "close_today", "close_yesterday"}:
            raise CompletionEvidenceError("managed request offset is unsupported")
        if request.account_id_masked is not None and not request.account_id_masked.strip():
            raise CompletionEvidenceError("managed account identity must be non-empty when supplied")
        if request.provider_session_id is not None and not request.provider_session_id.strip():
            raise CompletionEvidenceError("managed provider session must be non-empty when supplied")
        if request.trading_day is not None and not request.trading_day.strip():
            raise CompletionEvidenceError("managed trading day must be non-empty when supplied")
        if request.request_generation is not None and (
            not isinstance(request.request_generation, int)
            or isinstance(request.request_generation, bool)
            or request.request_generation < 1
        ):
            raise CompletionEvidenceError("managed request generation must be a positive integer")
        if request.intent_key is not None and not request.intent_key.strip():
            raise CompletionEvidenceError("managed intent key must be non-empty when supplied")

    provider_scope: tuple[str, str] | None = None
    all_native_sequences: list[int] = []
    all_native_times: list[datetime] = []
    for fact in evidence.order_facts:
        _validate_native_identity(
            event_id=fact.event_id,
            source=fact.source,
            session_id=fact.session_id,
            trading_day=fact.trading_day,
            sequence=fact.source_sequence,
            occurred_at_utc=fact.occurred_at_utc,
            evidence_sha256=fact.evidence_sha256,
        )
        if fact.callback_name != _CALLBACK_BY_FACT[fact.fact]:
            raise CompletionEvidenceError(
                f"{fact.fact.value} requires {_CALLBACK_BY_FACT[fact.fact]}"
            )
        if fact.status not in _STATUS_BY_FACT[fact.fact]:
            raise CompletionEvidenceError("native order status conflicts with typed fact")
        if not fact.order_ref or not fact.instrument_id:
            raise CompletionEvidenceError("native order fact requires ref and instrument")
        if fact.direction not in {None, "buy", "sell"}:
            raise CompletionEvidenceError("native order direction must be buy or sell")
        if fact.account_id_masked is not None and not fact.account_id_masked.strip():
            raise CompletionEvidenceError("native order account identity must be non-empty when supplied")
        if fact.offset not in {None, "open", "close", "close_today", "close_yesterday"}:
            raise CompletionEvidenceError("native order offset is unsupported")
        if fact.fact is not NativeOrderFactKind.REJECTED and not fact.external_order_id:
            raise CompletionEvidenceError("native order status requires external order id")
        traded, remaining = _decimal(fact.traded_quantity), _decimal(fact.remaining_quantity)
        if traded is None or remaining is None or traded < 0 or remaining < 0:
            raise CompletionEvidenceError("native order quantities must be finite and non-negative")
        if fact.fact is NativeOrderFactKind.ACCEPTED and remaining <= 0:
            raise CompletionEvidenceError("accepted order must remain open")
        if fact.fact is NativeOrderFactKind.PARTIAL and (traded <= 0 or remaining <= 0):
            raise CompletionEvidenceError("partial order requires traded and remaining quantity")
        if (
            fact.fact in {NativeOrderFactKind.CANCELED, NativeOrderFactKind.FILLED}
            and remaining != 0
        ):
            raise CompletionEvidenceError("terminal order must have zero remaining quantity")
        if fact.fact is NativeOrderFactKind.REJECTED and fact.error_id <= 0:
            raise CompletionEvidenceError("provider rejection requires positive ErrorID")
        provider_scope = _same_scope(provider_scope, (fact.session_id, fact.trading_day))
        all_native_sequences.append(fact.source_sequence)
        all_native_times.append(_parse_utc(fact.occurred_at_utc))

    for fact in evidence.trade_facts:
        _validate_native_identity(
            event_id=fact.event_id,
            source=fact.source,
            session_id=fact.session_id,
            trading_day=fact.trading_day,
            sequence=fact.source_sequence,
            occurred_at_utc=fact.occurred_at_utc,
            evidence_sha256=fact.evidence_sha256,
        )
        if fact.callback_name != "OnRtnTrade":
            raise CompletionEvidenceError("trade facts require OnRtnTrade")
        if fact.account_id_masked is not None and not fact.account_id_masked.strip():
            raise CompletionEvidenceError("native trade account identity must be non-empty when supplied")
        if (
            not fact.trade_id
            or not fact.order_ref
            or not fact.instrument_id
            or not fact.external_order_id
            or _decimal(fact.quantity) is None
            or fact.direction not in {"buy", "sell"}
            or fact.offset not in {None, "open", "close", "close_today", "close_yesterday"}
            or _decimal(fact.price) is None
        ):
            raise CompletionEvidenceError(
                "trade fact requires id, order/instrument, quantity, direction, and price"
            )
        if _decimal(fact.quantity) <= 0:
            raise CompletionEvidenceError("trade quantity must be positive")
        if _decimal(fact.price) <= 0:
            raise CompletionEvidenceError("trade price must be positive")
        provider_scope = _same_scope(provider_scope, (fact.session_id, fact.trading_day))
        all_native_sequences.append(fact.source_sequence)
        all_native_times.append(_parse_utc(fact.occurred_at_utc))

    if len(all_native_sequences) != len(set(all_native_sequences)):
        raise CompletionEvidenceError("native source sequence must be unique per case")
    native_event_ids = [fact.event_id for fact in (*evidence.order_facts, *evidence.trade_facts)]
    if len(native_event_ids) != len(set(native_event_ids)):
        raise CompletionEvidenceError(
            "native event_id must be unique across order and trade events"
        )
    events_by_sequence = sorted(
        (
            (fact.source_sequence, _parse_utc(fact.occurred_at_utc))
            for fact in (*evidence.order_facts, *evidence.trade_facts)
        ),
        key=lambda item: item[0],
    )
    if any(
        later_time < earlier_time
        for (_, earlier_time), (_, later_time) in zip(events_by_sequence, events_by_sequence[1:])
    ):
        raise CompletionEvidenceError("native event timestamps must not move backwards")

    for dependency in evidence.external_dependencies:
        if dependency.state not in {"satisfied", "unavailable"}:
            raise CompletionEvidenceError("external dependency state must be satisfied/unavailable")
        if not dependency.dependency_id or not dependency.evidence_ref:
            raise CompletionEvidenceError("external dependency requires id and evidence reference")
        if dependency.source != "control_plane_receipt":
            raise CompletionEvidenceError("external dependency requires control-plane source")
        if not _SHA256_RE.fullmatch(dependency.evidence_sha256):
            raise CompletionEvidenceError("external dependency requires SHA-256 evidence digest")
        if dependency.state == "unavailable" and not dependency.reason.strip():
            raise CompletionEvidenceError("unavailable dependency requires reason")

    phases = [snapshot.phase for snapshot in evidence.snapshots]
    if sorted(phase.value for phase in phases) != ["baseline", "final"]:
        raise CompletionEvidenceError("exactly one baseline and one final snapshot are required")
    baseline, final = _snapshots_by_phase(evidence.snapshots)
    for snapshot in (baseline, final):
        if not snapshot.session_id or not snapshot.trading_day:
            if not (
                evidence.case_id == "C01"
                and not c01_native_login_present
                and snapshot.session_id == ""
                and snapshot.trading_day == ""
            ):
                raise CompletionEvidenceError(
                    "account snapshot requires provider session and trading day"
                )
        if snapshot.account_id_masked is not None and not snapshot.account_id_masked.strip():
            raise CompletionEvidenceError("snapshot masked account identity must be non-empty when supplied")
        if provider_scope and (snapshot.session_id, snapshot.trading_day) != provider_scope:
            raise CompletionEvidenceError("snapshot provider scope does not match native callbacks")
        if _parse_utc(snapshot.occurred_at_utc) is None:
            raise CompletionEvidenceError("snapshot timestamp must carry UTC offset")
        if snapshot.phase is SnapshotPhase.FINAL:
            if any(
                _parse_utc(snapshot.occurred_at_utc) < _parse_utc(fact.occurred_at_utc)
                for fact in (*evidence.order_facts, *evidence.trade_facts)
            ):
                raise CompletionEvidenceError("final account snapshot predates a native event")
        elif snapshot.phase is SnapshotPhase.BASELINE:
            native_times = [
                _parse_utc(fact.occurred_at_utc)
                for fact in (*evidence.order_facts, *evidence.trade_facts)
            ]
            if native_times and _parse_utc(snapshot.occurred_at_utc) >= min(native_times):
                raise CompletionEvidenceError(
                    "baseline account snapshot must predate native activity"
                )
        if not all(
            (snapshot.order_query_id, snapshot.position_query_id, snapshot.account_query_id)
        ):
            raise CompletionEvidenceError("snapshot requires three native query ids")
        if not all(
            isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0
            for sequence in (
                snapshot.order_query_sequence,
                snapshot.position_query_sequence,
                snapshot.account_query_sequence,
            )
        ):
            raise CompletionEvidenceError("snapshot query sequences must be positive integers")
        if (
            len(
                {
                    snapshot.order_query_sequence,
                    snapshot.position_query_sequence,
                    snapshot.account_query_sequence,
                }
            )
            != 3
        ):
            raise CompletionEvidenceError("three query families require distinct source sequences")
        if (
            len(
                {
                    snapshot.order_query_id,
                    snapshot.position_query_id,
                    snapshot.account_query_id,
                }
            )
            != 3
        ):
            raise CompletionEvidenceError("three query families require distinct query ids")
        if snapshot.source != "ctp_provider_callback":
            raise CompletionEvidenceError("account snapshot must originate from provider callbacks")
        if evidence.case_id == "C01":
            if not snapshot.client_instance_id:
                raise CompletionEvidenceError("C01 query projection requires local client identity")
            if type(snapshot.arrival_generation) is not int or snapshot.arrival_generation < 1:
                raise CompletionEvidenceError("C01 query projection requires local arrival generation")
            if snapshot.query_id_origin != "local_query_coordinator":
                raise CompletionEvidenceError("C01 query IDs must be attributed to local coordinator")
            if not snapshot.query_round_id or snapshot.query_round_id_origin != "local_query_coordinator":
                raise CompletionEvidenceError("C01 query round ID must be locally attributed")
            if snapshot.sequence_origin != "local_sdk_callback_arrival":
                raise CompletionEvidenceError("C01 query sequences must be local callback arrivals")
            if snapshot.timestamp_origin != "local_sdk_capture_clock":
                raise CompletionEvidenceError("C01 query time must be local callback capture time")
            expected_scope_origin = (
                "derived_from_same_client_generation_native_login"
                if c01_native_login_present
                else ""
            )
            if snapshot.session_identity_origin != expected_scope_origin:
                raise CompletionEvidenceError(
                    "C01 query scope must derive from a native login when one is present"
                )
            if set(snapshot.query_native_request_ids) != _REQUIRED_QUERY_CALLBACKS or any(
                type(value) is not int or value <= 0
                for value in snapshot.query_native_request_ids.values()
            ):
                raise CompletionEvidenceError(
                    "C01 queries require positive native callback RequestIDs by query family"
                )
            if any(
                type(value) is not int or value != 0
                for value in snapshot.query_error_ids.values()
            ):
                raise CompletionEvidenceError("C01 native query ErrorIDs must be integer zero")
        if not _REQUIRED_QUERY_CALLBACKS.issubset(snapshot.callback_names):
            raise CompletionEvidenceError(
                "snapshot lacks complete native order/position/account query callbacks"
            )
        if set(snapshot.query_error_ids) != _REQUIRED_QUERY_CALLBACKS or any(
            isinstance(error_id, bool) or error_id != 0
            for error_id in snapshot.query_error_ids.values()
        ):
            raise CompletionEvidenceError("every native query callback must report ErrorID=0")
        if set(snapshot.query_is_last) != _REQUIRED_QUERY_CALLBACKS or any(
            value is not True for value in snapshot.query_is_last.values()
        ):
            raise CompletionEvidenceError(
                "each native query family must include its final callback marker"
            )
        if not _SHA256_RE.fullmatch(snapshot.evidence_sha256):
            raise CompletionEvidenceError("snapshot requires SHA-256 evidence digest")
        if any(not isinstance(ref, str) or not ref for ref in snapshot.open_order_refs):
            raise CompletionEvidenceError("snapshot open refs must be non-empty strings")
        if len(set(snapshot.open_order_refs)) != len(snapshot.open_order_refs):
            raise CompletionEvidenceError("snapshot contains duplicate open order refs")
        if set(snapshot.funds) != _REQUIRED_FUND_FIELDS:
            raise CompletionEvidenceError(
                "funds snapshot requires cash, available_funds, and equity"
            )
        if any(_decimal(value) is None for value in snapshot.funds.values()):
            raise CompletionEvidenceError("funds snapshot values must be finite decimals")
        if any(
            not instrument or _decimal(value) is None
            for instrument, value in snapshot.positions.items()
        ):
            raise CompletionEvidenceError(
                "positions snapshot requires instrument ids and finite quantities"
            )
        if any(
            not instrument or _decimal(value) is None or _decimal(value) < 0
            for instrument, value in snapshot.closeable_quantities.items()
        ):
            raise CompletionEvidenceError(
                "closeable quantities require instrument ids and finite non-negative values"
            )
        bucket_keys: set[tuple[str, str, str]] = set()
        for bucket in snapshot.closeable_position_buckets:
            if not isinstance(bucket, CloseablePositionBucket):
                raise CompletionEvidenceError("closeable position evidence must use typed buckets")
            if (
                not bucket.instrument_id.strip()
                or bucket.position_side not in {"long", "short"}
                or bucket.offset not in {"close_today", "close_yesterday"}
                or _decimal(bucket.quantity) is None
                or _decimal(bucket.quantity) < 0
            ):
                raise CompletionEvidenceError("closeable position bucket has invalid scope or quantity")
            bucket_key = (bucket.instrument_id, bucket.position_side, bucket.offset)
            if bucket_key in bucket_keys:
                raise CompletionEvidenceError("duplicate closeable position bucket")
            bucket_keys.add(bucket_key)
    if provider_scope and (baseline.session_id, baseline.trading_day) != provider_scope:
        raise CompletionEvidenceError("baseline snapshot session/day differs from callbacks")
    same_session = (baseline.session_id, baseline.trading_day) == (
        final.session_id,
        final.trading_day,
    )
    if evidence.case_id in {"M02", "M03"}:
        if baseline.trading_day != final.trading_day:
            raise CompletionEvidenceError("reconnect snapshots must use one trading day")
    elif not same_session:
        raise CompletionEvidenceError(
            "baseline and final snapshots must use one provider session/day"
        )
    if _parse_utc(final.occurred_at_utc) <= _parse_utc(baseline.occurred_at_utc):
        raise CompletionEvidenceError("final account snapshot must be later than baseline")
    if same_session:
        if not (
            baseline.order_query_sequence < final.order_query_sequence
            and baseline.position_query_sequence < final.position_query_sequence
            and baseline.account_query_sequence < final.account_query_sequence
        ):
            raise CompletionEvidenceError("final snapshots must be fresh queries after baseline")
        if {
            baseline.order_query_id,
            baseline.position_query_id,
            baseline.account_query_id,
        } & {
            final.order_query_id,
            final.position_query_id,
            final.account_query_id,
        }:
            raise CompletionEvidenceError("baseline and final query identifiers must be distinct")


def _check_reconnect_scope(
    evidence: CompletionEvidence,
    baseline: AccountReconciliationSnapshot,
    final: AccountReconciliationSnapshot,
    missing: list[str],
    contradictions: list[str],
) -> None:
    """Correlate an M03 session transition across callbacks and both queries.

    Query request IDs and source sequences can restart with a native session,
    so their identity is scoped to the session, not compared across it.
    """

    if baseline.session_id == final.session_id:
        missing.append("reconnect_snapshots_require_distinct_provider_sessions")
    rows = [
        row for row in evidence.scenario_evidence if row.event_kind == "store_reconnect_success"
    ]
    disconnects = [
        row for row in evidence.scenario_evidence if row.event_kind == "store_disconnected"
    ]
    if len(rows) != 1 or len(disconnects) != 1:
        if rows or disconnects:
            contradictions.append("reconnect_requires_one_disconnect_and_restore_transition")
        return
    row, disconnected = rows[0], disconnects[0]
    if (
        disconnected.provider_session_id != baseline.session_id
        or disconnected.trading_day != baseline.trading_day
        or disconnected.fields.get("gateway_key") != row.fields.get("gateway_key")
        or row.fields.get("previous_session_id") != baseline.session_id
        or row.fields.get("new_session_id") != final.session_id
        or row.provider_session_id != final.session_id
        or row.trading_day != final.trading_day
    ):
        contradictions.append("reconnect_event_does_not_match_snapshot_sessions")
    old_generation = disconnected.fields.get("connection_generation")
    new_generation = row.fields.get("connection_generation")
    if (
        type(old_generation) is not int
        or old_generation < 1
        or type(new_generation) is not int
        or new_generation <= old_generation
        or row.fields.get("previous_connection_generation") != old_generation
        or row.fields.get("new_connection_generation") != new_generation
    ):
        contradictions.append("reconnect_requires_new_connection_generation")
    baseline_time = _parse_utc(baseline.occurred_at_utc)
    disconnect_time = _parse_utc(disconnected.occurred_at_utc)
    reconnect_time = _parse_utc(row.occurred_at_utc)
    final_time = _parse_utc(final.occurred_at_utc)
    if not baseline_time < disconnect_time < reconnect_time < final_time:
        contradictions.append("reconnect_event_must_separate_account_snapshots")
    if any(
        sequence >= disconnected.source_sequence
        for sequence in (
            baseline.order_query_sequence,
            baseline.position_query_sequence,
            baseline.account_query_sequence,
        )
    ):
        contradictions.append("baseline_account_queries_must_precede_disconnect_callback")
    if any(
        sequence <= row.source_sequence
        for sequence in (
            final.order_query_sequence,
            final.position_query_sequence,
            final.account_query_sequence,
        )
    ):
        missing.append("final_account_queries_must_follow_reconnect_callback")
    dependency = next(
        (
            item
            for item in evidence.external_dependencies
            if item.dependency_id == "external_reconnect"
        ),
        None,
    )
    if (
        dependency is not None
        and dependency.state == "satisfied"
        and (
            dependency.fields.get("previous_session_id") != baseline.session_id
            or dependency.fields.get("new_session_id") != final.session_id
            or dependency.fields.get("gateway_key") != row.fields.get("gateway_key")
            or dependency.fields.get("disconnect_event_ref") != disconnected.event_id
            or dependency.fields.get("reconnect_event_ref") != row.event_id
            or dependency.fields.get("previous_connection_generation") != old_generation
            or dependency.fields.get("new_connection_generation") != new_generation
        )
    ):
        contradictions.append("reconnect_control_receipt_does_not_match_snapshot_sessions")


def _check_disconnect_restoration(
    evidence: CompletionEvidence,
    baseline: AccountReconciliationSnapshot,
    final: AccountReconciliationSnapshot,
    missing: list[str],
    contradictions: list[str],
) -> None:
    """Require M02's final account queries to follow a sourced restoration."""

    if baseline.session_id == final.session_id:
        missing.append("disconnect_restoration_requires_new_provider_session")
    disconnects = [
        row for row in evidence.scenario_evidence if row.event_kind == "store_disconnected"
    ]
    reconnects = [
        row for row in evidence.scenario_evidence if row.event_kind == "store_reconnect_success"
    ]
    if len(disconnects) != 1 or len(reconnects) != 1:
        if disconnects or reconnects:
            contradictions.append("disconnect_restoration_requires_one_callback_transition")
        return
    disconnected, reconnected = disconnects[0], reconnects[0]
    if (
        disconnected.provider_session_id != baseline.session_id
        or disconnected.trading_day != baseline.trading_day
        or reconnected.provider_session_id != final.session_id
        or reconnected.trading_day != final.trading_day
        or reconnected.fields.get("previous_session_id") != baseline.session_id
        or reconnected.fields.get("new_session_id") != final.session_id
        or disconnected.fields.get("gateway_key") != reconnected.fields.get("gateway_key")
    ):
        contradictions.append("disconnect_restore_callbacks_do_not_match_snapshot_sessions")
    old_generation = disconnected.fields.get("connection_generation")
    new_generation = reconnected.fields.get("connection_generation")
    if (
        type(old_generation) is not int
        or old_generation < 1
        or type(new_generation) is not int
        or new_generation <= old_generation
        or reconnected.fields.get("previous_connection_generation") != old_generation
        or reconnected.fields.get("new_connection_generation") != new_generation
    ):
        contradictions.append("disconnect_restoration_requires_new_connection_generation")
    if not (
        _parse_utc(baseline.occurred_at_utc)
        < _parse_utc(disconnected.occurred_at_utc)
        < _parse_utc(reconnected.occurred_at_utc)
        < _parse_utc(final.occurred_at_utc)
    ):
        contradictions.append("disconnect_restore_callbacks_must_separate_account_snapshots")
    if any(
        sequence >= disconnected.source_sequence
        for sequence in (
            baseline.order_query_sequence,
            baseline.position_query_sequence,
            baseline.account_query_sequence,
        )
    ):
        contradictions.append("baseline_account_queries_must_precede_disconnect_callback")
    if any(
        sequence <= reconnected.source_sequence
        for sequence in (
            final.order_query_sequence,
            final.position_query_sequence,
            final.account_query_sequence,
        )
    ):
        missing.append("final_account_queries_must_follow_restored_session")
    dependency = next(
        (
            item
            for item in evidence.external_dependencies
            if item.dependency_id == "external_disconnect"
        ),
        None,
    )
    if (
        dependency is not None
        and dependency.state == "satisfied"
        and (
            dependency.fields.get("session_id") != baseline.session_id
            or dependency.fields.get("gateway_key") != disconnected.fields.get("gateway_key")
            or dependency.fields.get("provider_event_ref") != disconnected.event_id
            or dependency.fields.get("connection_generation") != old_generation
        )
    ):
        contradictions.append("disconnect_control_receipt_does_not_match_provider_event")


def _derive_invariants(
    evidence: CompletionEvidence, expectation: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    contradictions: list[str] = []
    case_id = evidence.case_id
    if case_id in {"V01", "V02", "V03"}:
        validation_rows = [
            row
            for row in evidence.scenario_evidence
            if row.event_kind == "order_validation_rejected"
        ]
        if len(validation_rows) != 1:
            missing.append("validation_case_requires_exactly_one_local_rejection_record")
        for row in validation_rows:
            row_missing, row_contradictions = validation_failure_conditions(
                case_id, row.fields, row.occurred_at_utc
            )
            missing.extend(row_missing)
            contradictions.extend(row_contradictions)
    baseline, final = _snapshots_by_phase(evidence.snapshots)
    _check_o02_close_semantics(evidence, baseline, final, missing, contradictions)
    baseline_time = _parse_utc(baseline.occurred_at_utc)
    final_time = _parse_utc(final.occurred_at_utc)
    if case_id == "C01":
        auth_rows = [
            row for row in evidence.scenario_evidence if row.event_kind == "store_auth_success"
        ]
        login_rows = [
            row for row in evidence.scenario_evidence if row.event_kind == "store_login_success"
        ]
        if len(auth_rows) != 1 or len(login_rows) != 1:
            missing.append("exactly_one_provider_auth_and_login_callback_required")
        else:
            auth, login = auth_rows[0], login_rows[0]
            auth_arrival = auth.callback_arrival
            login_arrival = login.callback_arrival
            if auth_arrival is None or login_arrival is None:
                missing.append("auth_and_login_require_local_callback_arrival_metadata")
            else:
                if (
                    auth_arrival.client_instance_id != login_arrival.client_instance_id
                    or auth_arrival.arrival_generation != login_arrival.arrival_generation
                ):
                    contradictions.append(
                        "auth_and_login_must_share_client_and_arrival_generation"
                    )
                auth_request_id = auth.fields.get("request_id")
                login_request_id = login.fields.get("request_id")
                if (
                    type(auth_request_id) is not int
                    or type(login_request_id) is not int
                    or auth_request_id == login_request_id
                ):
                    contradictions.append("auth_login_native_request_ids_must_be_distinct")
                for row, arrival, request_kind, request_id in (
                    (auth, auth_arrival, "authenticate", auth_request_id),
                    (login, login_arrival, "login", login_request_id),
                ):
                    if not validate_issued_request_receipt(
                        arrival.issued_request_receipt,
                        request_kind=request_kind,
                        phase="",
                        request_id=request_id,
                        request_generation=arrival.request_generation,
                        client_instance_id=arrival.client_instance_id,
                        arrival_generation=arrival.arrival_generation,
                        arrived_at_utc=arrival.arrived_at_utc,
                        arrived_monotonic=arrival.arrived_monotonic,
                    ):
                        missing.append(f"{request_kind}_requires_matching_typed_issued_request_receipt")
                if (
                    auth_arrival.source_sequence >= login_arrival.source_sequence
                    or auth_arrival.request_generation == login_arrival.request_generation
                    or _parse_utc(auth_arrival.arrived_at_utc)
                    >= _parse_utc(login_arrival.arrived_at_utc)
                ):
                    contradictions.append(
                        "authentication_arrival_must_precede_distinct_login_request"
                    )
                all_query_ids = []
                for snapshot in (baseline, final):
                    if (
                        snapshot.client_instance_id != login_arrival.client_instance_id
                        or snapshot.arrival_generation != login_arrival.arrival_generation
                    ):
                        contradictions.append(
                            f"{snapshot.phase.value}_queries_must_share_login_client_generation"
                        )
                    expected_families = {
                        "orders": "OnRspQryOrder",
                        "positions": "OnRspQryInvestorPosition",
                        "funds": "OnRspQryTradingAccount",
                    }
                    all_query_ids.extend(
                        snapshot.query_native_request_ids.get(callback)
                        for callback in expected_families.values()
                    )
                    if set(snapshot.query_issued_request_receipts) != set(expected_families.values()):
                        missing.append(
                            f"{snapshot.phase.value}_queries_require_typed_issued_request_receipts"
                        )
                    for family, callback in expected_families.items():
                        receipt = snapshot.query_issued_request_receipts.get(callback)
                        request_generation = snapshot.query_request_generations.get(callback)
                        arrived_at = snapshot.query_arrival_times_utc.get(callback)
                        arrived_monotonic = snapshot.query_arrival_monotonic.get(callback)
                        if not validate_issued_request_receipt(
                            receipt,
                            request_kind=family,
                            phase=snapshot.phase.value,
                            request_id=snapshot.query_native_request_ids.get(callback),
                            request_generation=request_generation,
                            client_instance_id=snapshot.client_instance_id,
                            arrival_generation=snapshot.arrival_generation,
                            arrived_at_utc=arrived_at,
                            arrived_monotonic=arrived_monotonic,
                        ):
                            missing.append(
                                f"{snapshot.phase.value}_{family}_query_receipt_does_not_match_callback"
                            )
                if (
                    len(all_query_ids) != 6
                    or any(type(item) is not int or item <= 0 for item in all_query_ids)
                    or len(set(all_query_ids)) != 6
                ):
                    contradictions.append("C01 baseline/final queries require six distinct native RequestIDs")
                if (
                    login.provider_session_id != baseline.session_id
                    or login.trading_day != baseline.trading_day
                    or login.provider_session_id != final.session_id
                    or login.trading_day != final.trading_day
                ):
                    contradictions.append("login_native_scope_must_match_account_queries")
                if (
                    _parse_utc(login_arrival.arrived_at_utc) >= baseline_time
                    or login_arrival.source_sequence
                    >= min(
                        baseline.order_query_sequence,
                        baseline.position_query_sequence,
                        baseline.account_query_sequence,
                    )
                ):
                    contradictions.append("login_must_precede_baseline_query_arrivals")
    for request in evidence.managed_requests:
        request_time = _parse_utc(request.occurred_at_utc)
        if not baseline_time < request_time < final_time:
            contradictions.append(
                f"managed_request_outside_account_snapshot_window:{request.request_id}"
            )
        if request.dispatch_state is DispatchState.DISPATCHED:
            if request.action is RequestAction.SUBMIT:
                corresponding = [
                    fact for fact in evidence.order_facts if fact.order_ref == request.order_refs[0]
                ]
                if corresponding and request_time > min(
                    _parse_utc(fact.occurred_at_utc) for fact in corresponding
                ):
                    contradictions.append(
                        f"managed_submit_after_native_order_callback:{request.request_id}"
                    )
            else:
                canceled = [
                    fact
                    for fact in evidence.order_facts
                    if fact.fact is NativeOrderFactKind.CANCELED
                    and fact.order_ref in request.order_refs
                ]
                if canceled and request_time > min(
                    _parse_utc(fact.occurred_at_utc) for fact in canceled
                ):
                    contradictions.append(
                        f"managed_cancel_after_native_cancel_callback:{request.request_id}"
                    )
    if case_id == "M02":
        _check_disconnect_restoration(evidence, baseline, final, missing, contradictions)
    if case_id == "M03":
        _check_reconnect_scope(evidence, baseline, final, missing, contradictions)
    dispatched_submits = [
        request
        for request in evidence.managed_requests
        if request.action is RequestAction.SUBMIT
        and request.dispatch_state is DispatchState.DISPATCHED
    ]
    submit_refs = [request.order_refs[0] for request in dispatched_submits]
    submit_ref_set = set(submit_refs)
    all_provider_refs = {fact.order_ref for fact in evidence.order_facts}
    all_trade_refs = {fact.order_ref for fact in evidence.trade_facts}
    if len(submit_refs) != len(submit_ref_set):
        contradictions.append("one_order_ref_has_multiple_dispatched_submit_receipts")
    if all_provider_refs - submit_ref_set:
        contradictions.append("provider_order_fact_without_managed_submit_receipt")
    if all_trade_refs - submit_ref_set:
        contradictions.append("trade_without_managed_submit_receipt")

    for dependency in evidence.external_dependencies:
        order_ref = dependency.fields.get("order_ref")
        if order_ref and order_ref not in submit_ref_set:
            contradictions.append(
                f"external_condition_order_ref_without_dispatched_submit:{dependency.dependency_id}"
            )

    order_expectation = str(expectation.get("order_activity", ""))
    trade_expectation = str(expectation.get("trade_activity", ""))
    _check_external_dependencies(evidence, missing, contradictions)
    minimum_refs = 2 if case_id in {"B01", "B02"} else 1
    if order_expectation == "none":
        if dispatched_submits or evidence.order_facts or evidence.trade_facts:
            contradictions.append("provider_order_activity_present_for_no_order_case")
    elif order_expectation == "required":
        if len(submit_ref_set) < minimum_refs:
            missing.append(f"minimum_dispatched_order_refs:{minimum_refs}")
        if not dispatched_submits:
            missing.append("managed_dispatched_submit_receipt")
        if not evidence.order_facts:
            missing.append("native_provider_order_activity")

    if trade_expectation == "required" and not evidence.trade_facts:
        missing.append("required_native_trade_activity")
    if trade_expectation == "none" and evidence.trade_facts:
        contradictions.append("native_trade_activity_for_no_trade_case")

    requests_for_cancel = [
        request
        for request in evidence.managed_requests
        if request.action in {RequestAction.CANCEL, RequestAction.BATCH_CANCEL}
        and request.dispatch_state is DispatchState.DISPATCHED
    ]
    cancel_refs = {ref for request in requests_for_cancel for ref in request.order_refs}
    blocked_cancel_requests = [
        request
        for request in evidence.managed_requests
        if request.action is RequestAction.CANCEL
        and request.dispatch_state is DispatchState.BLOCKED_PRE_DISPATCH
    ]
    if case_id in {"O01", "O02"}:
        repeat_attempts = [
            request
            for request in evidence.managed_requests
            if request.action is RequestAction.SUBMIT
        ]
        blocked_repeats = [
            request
            for request in repeat_attempts
            if request.dispatch_state is DispatchState.BLOCKED_PRE_DISPATCH
        ]
        if len(repeat_attempts) < 2 or not blocked_repeats:
            missing.append("repeat_scenario_requires_second_submit_blocked_pre_dispatch")
        elif not any(
            request.dispatch_state is DispatchState.DISPATCHED
            and request.order_refs == blocked_repeats[0].order_refs
            for request in repeat_attempts
        ):
            contradictions.append("repeat_submit_must_target_the_same_intent_key")
    if case_id == "O03":
        repeat_cancel_attempts = [
            request
            for request in evidence.managed_requests
            if request.action is RequestAction.CANCEL
        ]
        if len(repeat_cancel_attempts) < 2 or not blocked_cancel_requests:
            missing.append("repeat_cancel_requires_second_attempt_blocked_pre_dispatch")
        if not any(
            request.action is RequestAction.CANCEL
            and request.dispatch_state is DispatchState.DISPATCHED
            for request in evidence.managed_requests
        ):
            missing.append("repeat_cancel_requires_first_dispatched_cancel")
        dispatched_cancel = next(
            (
                request
                for request in evidence.managed_requests
                if request.action is RequestAction.CANCEL
                and request.dispatch_state is DispatchState.DISPATCHED
            ),
            None,
        )
        blocked_cancel = next(iter(blocked_cancel_requests), None)
        if (
            dispatched_cancel
            and blocked_cancel
            and dispatched_cancel.order_refs != blocked_cancel.order_refs
        ):
            contradictions.append("repeat_cancel_must_target_the_same_order_ref")
    if case_id in {"M05", "T03", "TH04"} and not any(
        request.action is RequestAction.CANCEL
        and request.dispatch_state is DispatchState.DISPATCHED
        for request in evidence.managed_requests
    ):
        missing.append("managed_dispatched_cancel_receipt")

    if case_id in {"B01", "B02"}:
        batch_requests = [
            request
            for request in evidence.managed_requests
            if request.action is RequestAction.BATCH_CANCEL
            and request.dispatch_state is DispatchState.DISPATCHED
        ]
        if not batch_requests:
            missing.append("native_batch_cancel_request_receipt")
        else:
            batch_refs = {ref for request in batch_requests for ref in request.order_refs}
            if batch_refs != submit_ref_set:
                contradictions.append("batch_cancel_refs_must_exactly_match_submitted_orders")
            if len(batch_requests) != 1:
                contradictions.append("exactly_one_dispatched_batch_cancel_receipt_required")
    for fact in evidence.order_facts:
        if fact.fact is NativeOrderFactKind.CANCELED and fact.order_ref not in cancel_refs:
            contradictions.append(
                f"canceled_order_without_dispatched_cancel_request:{fact.order_ref}"
            )
    for request in requests_for_cancel:
        if not set(request.order_refs).issubset(submit_ref_set):
            contradictions.append("cancel_request_references_unsubmitted_order")

    by_order: dict[str, list[NativeOrderFact]] = {}
    for fact in evidence.order_facts:
        by_order.setdefault(fact.order_ref, []).append(fact)
    trades_by_order: dict[str, list[NativeTradeFact]] = {}
    for trade in evidence.trade_facts:
        trades_by_order.setdefault(trade.order_ref, []).append(trade)

    for order_ref in sorted(submit_ref_set):
        facts = sorted(by_order.get(order_ref, []), key=lambda item: item.source_sequence)
        terminal = [fact for fact in facts if fact.fact in _TERMINAL_FACTS]
        if not facts or not terminal:
            missing.append(f"provider_terminal_order_state:{order_ref}")
            continue
        submit = next(
            request for request in dispatched_submits if request.order_refs[0] == order_ref
        )
        requested_quantity = _decimal(submit.quantity)
        if any(
            (_decimal(fact.traded_quantity) or Decimal(0)) > requested_quantity for fact in facts
        ):
            contradictions.append(f"provider_traded_quantity_exceeds_request:{order_ref}")
        for fact in facts:
            traded = _decimal(fact.traded_quantity) or Decimal(0)
            remaining = _decimal(fact.remaining_quantity) or Decimal(0)
            if fact.fact in {NativeOrderFactKind.ACCEPTED, NativeOrderFactKind.PARTIAL}:
                if traded + remaining != requested_quantity:
                    contradictions.append(
                        f"provider_open_quantity_conservation_mismatch:{order_ref}"
                    )
            elif fact.fact is NativeOrderFactKind.FILLED and traded != requested_quantity:
                contradictions.append(
                    f"provider_filled_quantity_does_not_match_request:{order_ref}"
                )
        if any(
            fact.instrument_id != facts[0].instrument_id
            or fact.external_order_id != facts[0].external_order_id
            for fact in facts
        ):
            contradictions.append(f"provider_order_identity_changed:{order_ref}")
        if any(
            (_decimal(current.traded_quantity) or Decimal(0))
            < (_decimal(previous.traded_quantity) or Decimal(0))
            for previous, current in zip(facts, facts[1:])
        ):
            contradictions.append(f"provider_cumulative_trade_quantity_decreased:{order_ref}")
        latest = facts[-1]
        if latest.fact not in _TERMINAL_FACTS:
            missing.append(f"latest_provider_order_fact_not_terminal:{order_ref}")
            continue
        if (
            latest.fact is NativeOrderFactKind.REJECTED
            and expectation.get("order_activity") == "required"
            and case_id not in _EXPECTED_REMOTE_REJECTION_CASES
        ):
            contradictions.append(f"unexpected_provider_rejection_for_order_scenario:{order_ref}")
        if case_id == "T03" and latest.fact is not NativeOrderFactKind.CANCELED:
            contradictions.append(f"cancel_scenario_did_not_end_canceled:{order_ref}")
        if case_id == "B01" and latest.fact is not NativeOrderFactKind.CANCELED:
            contradictions.append(f"partial_batch_case_did_not_end_canceled:{order_ref}")
        if case_id == "B01":
            if not any(fact.fact is NativeOrderFactKind.PARTIAL for fact in facts):
                missing.append(f"partial_fill_required:{order_ref}")
        if (
            case_id in _EXPECTED_REMOTE_REJECTION_CASES
            and latest.fact is not NativeOrderFactKind.REJECTED
        ):
            contradictions.append(f"external_rejection_case_not_rejected:{order_ref}")
        if latest.fact in {
            NativeOrderFactKind.CANCELED,
            NativeOrderFactKind.FILLED,
            NativeOrderFactKind.PARTIAL,
        }:
            traded = _decimal(latest.traded_quantity)
            trade_sum = sum(
                (_decimal(item.quantity) or Decimal(0))
                for item in trades_by_order.get(order_ref, [])
            )
            if traded is None or traded != trade_sum:
                contradictions.append(f"terminal_trade_quantity_mismatch:{order_ref}")
            if requested_quantity is not None and trade_sum > requested_quantity:
                contradictions.append(f"native_trade_quantity_exceeds_request:{order_ref}")
            if any(
                item.instrument_id != latest.instrument_id
                for item in trades_by_order.get(order_ref, [])
            ):
                contradictions.append(f"trade_instrument_mismatch:{order_ref}")
            if any(
                item.external_order_id != latest.external_order_id
                for item in trades_by_order.get(order_ref, [])
            ):
                contradictions.append(f"trade_external_order_id_mismatch:{order_ref}")
        if latest.fact in {
            NativeOrderFactKind.PARTIAL,
            NativeOrderFactKind.FILLED,
        } and not trades_by_order.get(order_ref):
            missing.append(f"provider_trade_callback_required:{order_ref}")
        accepted = [fact for fact in facts if fact.fact is NativeOrderFactKind.ACCEPTED]
        if latest.fact is not NativeOrderFactKind.REJECTED and not accepted:
            missing.append(f"provider_acceptance_callback:{order_ref}")
        if accepted and any(
            trade.source_sequence <= min(fact.source_sequence for fact in accepted)
            for trade in trades_by_order.get(order_ref, [])
        ):
            contradictions.append(f"trade_precedes_provider_acceptance:{order_ref}")

    final_order_events = [
        *evidence.order_facts,
        *evidence.trade_facts,
    ]
    latest_provider_sequence = max((item.source_sequence for item in final_order_events), default=0)
    if expectation.get("no_open_orders_after") is True and final.open_order_refs:
        contradictions.append("provider_open_orders_remain_after_cleanup")
    if order_expectation == "none" and set(baseline.open_order_refs) != set(final.open_order_refs):
        contradictions.append("open_order_refs_changed_without_case_order_activity")
    if final.order_query_sequence <= latest_provider_sequence:
        missing.append("final_order_query_must_follow_all_native_order_and_trade_events")
    if final.position_query_sequence <= latest_provider_sequence:
        missing.append("final_position_query_must_follow_all_native_order_and_trade_events")
    if final.account_query_sequence <= latest_provider_sequence:
        missing.append("final_account_query_must_follow_all_native_order_and_trade_events")
    first_provider_sequence = min(
        (item.source_sequence for item in final_order_events), default=None
    )
    if first_provider_sequence is not None and (
        baseline.order_query_sequence >= first_provider_sequence
        or baseline.position_query_sequence >= first_provider_sequence
        or baseline.account_query_sequence >= first_provider_sequence
    ):
        missing.append("baseline_order_position_account_queries_must_precede_native_activity")

    has_trades = bool(evidence.trade_facts)
    position_policy = expectation.get("account_position_change")
    baseline_positions = _decimal_mapping(baseline.positions)
    final_positions = _decimal_mapping(final.positions)
    unchanged_positions = baseline_positions == final_positions
    unchanged_funds = _decimal_mapping(baseline.funds) == _decimal_mapping(final.funds)
    if position_policy == "none" and (not unchanged_positions or not unchanged_funds):
        contradictions.append("positions_or_funds_changed_for_no_change_case")
    elif position_policy == "allowed_if_trade" and not has_trades:
        if not unchanged_positions or not unchanged_funds:
            contradictions.append("positions_or_funds_changed_without_trade_callback")
    elif position_policy == "allowed_if_trade" and baseline_positions is not None:
        expected_positions = dict(baseline_positions)
        for trade in evidence.trade_facts:
            quantity = _decimal(trade.quantity) or Decimal(0)
            signed_quantity = quantity if trade.direction == "buy" else -quantity
            expected_positions[trade.instrument_id] = (
                expected_positions.get(trade.instrument_id, Decimal(0)) + signed_quantity
            )
        expected_positions = {
            instrument: quantity
            for instrument, quantity in expected_positions.items()
            if quantity != 0
        }
        actual_positions = {
            instrument: quantity
            for instrument, quantity in (final_positions or {}).items()
            if quantity != 0
        }
        if final_positions is None or actual_positions != expected_positions:
            contradictions.append("final_net_positions_do_not_match_provider_trade_delta")
    if trade_expectation == "none" and (not unchanged_positions or not unchanged_funds):
        contradictions.append("positions_or_funds_changed_without_permitted_trade")

    return missing, contradictions


def _check_o02_close_semantics(
    evidence: CompletionEvidence,
    baseline: AccountReconciliationSnapshot,
    final: AccountReconciliationSnapshot,
    missing: list[str],
    contradictions: list[str],
) -> None:
    """Require one scoped O02 close and a blocked repeat backed by a CTP bucket.

    Scalar net position and closeable-by-instrument maps cannot prove CTP
    long/short or close-today/close-yesterday availability. O02 therefore
    supports only explicitly bucketed ``close_today`` and ``close_yesterday``
    requests; generic ``close`` remains incomplete until an adapter can supply
    a typed bucket for its actual CTP semantics.
    """

    if evidence.case_id != "O02":
        return
    attempts = [
        request
        for request in evidence.managed_requests
        if request.action is RequestAction.SUBMIT
    ]
    if not attempts:
        return  # The general order invariants report the missing submit.

    dispatched = [
        request
        for request in attempts
        if request.dispatch_state is DispatchState.DISPATCHED
    ]
    blocked = [
        request
        for request in attempts
        if request.dispatch_state is DispatchState.BLOCKED_PRE_DISPATCH
    ]
    if len(attempts) != 2 or len(dispatched) != 1 or len(blocked) != 1:
        contradictions.append("o02_requires_exactly_one_dispatched_and_one_blocked_submit")
        return

    first, repeat = dispatched[0], blocked[0]
    if len(first.order_refs) != 1 or first.order_refs != repeat.order_refs:
        contradictions.append("o02_blocked_repeat_must_match_dispatched_order_ref")

    scoped_fields = (
        ("account_id_masked", first.account_id_masked, repeat.account_id_masked),
        ("provider_session_id", first.provider_session_id, repeat.provider_session_id),
        ("trading_day", first.trading_day, repeat.trading_day),
        ("intent_key", first.intent_key, repeat.intent_key),
        ("instrument_id", first.instrument_id, repeat.instrument_id),
        ("direction", first.direction, repeat.direction),
        ("offset", first.offset, repeat.offset),
    )
    for field_name, left, right in scoped_fields:
        if not left or left != right:
            contradictions.append(f"o02_repeat_{field_name}_must_match_and_be_present")

    first_quantity = _decimal(first.quantity)
    repeat_quantity = _decimal(repeat.quantity)
    if first_quantity is None or repeat_quantity is None or first_quantity != repeat_quantity:
        contradictions.append("o02_repeat_quantity_must_match")
    if (
        first.request_generation is None
        or repeat.request_generation is None
        or repeat.request_generation <= first.request_generation
        or repeat.sequence <= first.sequence
        or _parse_utc(repeat.occurred_at_utc) <= _parse_utc(first.occurred_at_utc)
    ):
        contradictions.append("o02_blocked_repeat_must_follow_first_request_generation")

    repeat_rows = [
        row
        for row in evidence.scenario_evidence
        if row.event_kind == "risk_repeat_order_detected"
    ]
    if len(repeat_rows) != 1:
        missing.append("o02_requires_one_repeat_monitor_event")
    elif (
        repeat_rows[0].fields.get("repeat_key") != first.intent_key
        or repeat_rows[0].fields.get("repeat_count") != 2
        or repeat_rows[0].fields.get("account_id_masked") != first.account_id_masked
        or repeat_rows[0].fields.get("provider_session_id") != first.provider_session_id
        or repeat_rows[0].fields.get("trading_day") != first.trading_day
    ):
        contradictions.append("o02_repeat_monitor_must_match_submit_scope_and_intent")

    if first.instrument_id is None or first.direction is None or first.offset is None:
        missing.append("o02_submit_requires_instrument_direction_and_offset")
        return
    if first.offset not in {"close_today", "close_yesterday"}:
        missing.append("o02_requires_typed_close_today_or_close_yesterday_bucket")
    expected_side = "long" if first.direction == "sell" else "short"
    expected_direction = "sell" if expected_side == "long" else "buy"
    if first.direction != expected_direction:
        contradictions.append("o02_close_direction_must_match_held_position_side")

    if not baseline.account_id_masked or not final.account_id_masked:
        missing.append("o02_requires_account_identity_on_baseline_and_final_snapshots")
    elif baseline.account_id_masked != final.account_id_masked:
        contradictions.append("o02_account_identity_changed_between_snapshots")
    if (
        not baseline.account_id_masked
        or first.account_id_masked != baseline.account_id_masked
        or repeat.account_id_masked != baseline.account_id_masked
    ):
        contradictions.append("o02_request_account_must_match_account_snapshots")
    if (
        not first.provider_session_id
        or first.provider_session_id != baseline.session_id
        or first.provider_session_id != final.session_id
    ):
        contradictions.append("o02_request_provider_session_must_match_account_snapshots")
    if (
        not first.trading_day
        or first.trading_day != baseline.trading_day
        or first.trading_day != final.trading_day
    ):
        contradictions.append("o02_request_trading_day_must_match_account_snapshots")

    instrument_offset_buckets = [
        bucket
        for bucket in baseline.closeable_position_buckets
        if bucket.instrument_id == first.instrument_id and bucket.offset == first.offset
    ]
    matching_buckets = [
        bucket for bucket in instrument_offset_buckets if bucket.position_side == expected_side
    ]
    if len(matching_buckets) != 1:
        if instrument_offset_buckets:
            contradictions.append("o02_close_direction_does_not_match_available_position_side")
        else:
            missing.append("o02_requires_matching_baseline_side_and_offset_closeable_bucket")
        available = None
    else:
        available = _decimal(matching_buckets[0].quantity)
        if available is None or available <= 0:
            contradictions.append("o02_requires_positive_baseline_closeable_bucket")
            available = None

    if first_quantity is not None and available is not None and first_quantity > available:
        contradictions.append("o02_requested_close_quantity_exceeds_baseline_bucket")

    order_ref = first.order_refs[0] if len(first.order_refs) == 1 else None
    for fact in evidence.order_facts:
        if fact.order_ref != order_ref:
            continue
        if (fact.session_id, fact.trading_day) != (baseline.session_id, baseline.trading_day) or (
            fact.session_id, fact.trading_day
        ) != (final.session_id, final.trading_day):
            contradictions.append("o02_native_order_provider_scope_mismatch")
        if (
            not fact.account_id_masked
            or fact.account_id_masked != baseline.account_id_masked
            or fact.account_id_masked != final.account_id_masked
        ):
            contradictions.append("o02_native_order_account_must_match_account_snapshots")
        if fact.instrument_id != first.instrument_id:
            contradictions.append("o02_native_order_instrument_mismatch")
        if fact.direction is None or fact.offset is None:
            missing.append("o02_native_order_requires_direction_and_offset")
            continue
        if fact.direction != first.direction or fact.offset != first.offset:
            contradictions.append("o02_native_order_side_or_offset_mismatch")

    filled_quantity = Decimal(0)
    for trade in evidence.trade_facts:
        if trade.order_ref != order_ref:
            continue
        if (trade.session_id, trade.trading_day) != (baseline.session_id, baseline.trading_day) or (
            trade.session_id, trade.trading_day
        ) != (final.session_id, final.trading_day):
            contradictions.append("o02_native_trade_provider_scope_mismatch")
        if (
            not trade.account_id_masked
            or trade.account_id_masked != baseline.account_id_masked
            or trade.account_id_masked != final.account_id_masked
        ):
            contradictions.append("o02_native_trade_account_must_match_account_snapshots")
        if trade.instrument_id != first.instrument_id:
            contradictions.append("o02_trade_instrument_mismatch")
        if trade.direction != first.direction:
            contradictions.append("o02_trade_direction_mismatch")
        if trade.offset is None:
            missing.append("o02_trade_requires_close_offset")
        elif trade.offset != first.offset:
            contradictions.append("o02_trade_offset_must_match_submit")
        quantity = _decimal(trade.quantity)
        if quantity is not None:
            filled_quantity += quantity
    if available is not None and filled_quantity > available:
        contradictions.append("o02_filled_close_quantity_exceeds_baseline_bucket")

def _check_external_dependencies(
    evidence: CompletionEvidence,
    missing: list[str],
    contradictions: list[str],
) -> None:
    required = _REQUIRED_DEPENDENCIES.get(evidence.case_id, set())
    by_id = {dependency.dependency_id: dependency for dependency in evidence.external_dependencies}
    if len(by_id) != len(evidence.external_dependencies):
        contradictions.append("duplicate_external_dependency_receipt")
    if set(by_id) - required:
        contradictions.append("unexpected_external_dependency_receipt")
    for dependency_id in sorted(required):
        dependency = by_id.get(dependency_id)
        if dependency is None:
            missing.append(f"external_dependency:{dependency_id}")
            continue
        if dependency.state == "unavailable":
            continue
        fields = dependency.fields
        if dependency_id == "external_disconnect":
            if not all(
                fields.get(key) for key in ("gateway_key", "session_id", "provider_event_ref")
            ):
                missing.append("external_disconnect_requires_provider_session_event")
        elif dependency_id == "external_reconnect":
            previous = fields.get("previous_session_id")
            current = fields.get("new_session_id")
            if not fields.get("gateway_key") or not previous or not current:
                missing.append("external_reconnect_requires_old_and_new_session_ids")
            elif previous == current:
                contradictions.append("reconnect_must_create_a_new_provider_session")
        elif dependency_id == "insufficient_funds":
            available = _decimal(fields.get("available_funds"))
            required_margin = _decimal(fields.get("required_margin"))
            if not fields.get("instrument_id") or not fields.get("order_ref"):
                missing.append("insufficient_funds_requires_instrument_and_order_ref")
            if available is None or required_margin is None:
                missing.append("insufficient_funds_requires_numeric_funds_and_margin")
            elif available >= required_margin:
                contradictions.append("insufficient_funds_condition_not_physically_satisfied")
        elif dependency_id == "insufficient_position":
            available = _decimal(fields.get("available_closeable_quantity"))
            requested = _decimal(fields.get("requested_close_quantity"))
            if not fields.get("instrument_id") or not fields.get("order_ref"):
                missing.append("insufficient_position_requires_instrument_and_order_ref")
            if available is None or requested is None:
                missing.append("insufficient_position_requires_numeric_quantities")
            elif requested <= available:
                contradictions.append("insufficient_position_condition_not_physically_satisfied")
        elif dependency_id == "market_state":
            if not fields.get("instrument_id") or not fields.get("order_ref"):
                missing.append("market_state_requires_instrument_and_order_ref")
            if fields.get("tradable") is not False or not fields.get("provider_market_event_ref"):
                missing.append("market_state_requires_nontrading_provider_observation")
        elif dependency_id == "account_permission_disabled":
            if fields.get("state") != "disabled" or not all(
                fields.get(key)
                for key in (
                    "account_id_masked",
                    "change_id",
                    "provider_audit_ref",
                    "occurred_at_utc",
                )
            ):
                missing.append("permission_disable_requires_admin_audit_and_masked_account")
            if _parse_utc(str(fields.get("occurred_at_utc", ""))) is None:
                missing.append("permission_disable_requires_utc_timestamp")
        elif dependency_id == "account_permission_restored":
            if fields.get("state") != "restored" or not all(
                fields.get(key)
                for key in (
                    "account_id_masked",
                    "change_id",
                    "provider_audit_ref",
                    "occurred_at_utc",
                )
            ):
                missing.append("permission_restore_requires_admin_audit_and_masked_account")
            if _parse_utc(str(fields.get("occurred_at_utc", ""))) is None:
                missing.append("permission_restore_requires_utc_timestamp")
        elif dependency_id == "strategy_pause_authorized":
            if (
                fields.get("state") != "paused"
                or not fields.get("strategy_id")
                or not fields.get("pause_event_ref")
                or fields.get("pending_orders_reconciled") is not True
            ):
                missing.append("strategy_pause_requires_authorized_pause_and_order_reconciliation")
        elif dependency_id == "gateway_force_logout_ack":
            if (
                fields.get("acknowledged") is not True
                or not fields.get("gateway_key")
                or not fields.get("session_id")
                or not fields.get("operator_audit_ref")
            ):
                missing.append("force_logout_requires_external_operator_ack_and_session_identity")
    if evidence.case_id == "EM01":
        disabled = by_id.get("account_permission_disabled")
        restored = by_id.get("account_permission_restored")
        rows = [
            row
            for row in evidence.scenario_evidence
            if row.event_kind == "account_trading_disabled"
        ]
        if disabled and disabled.state == "satisfied" and len(rows) == 1:
            row = rows[0]
            if (
                disabled.fields.get("account_id_masked") != row.fields.get("account_id_masked")
                or disabled.fields.get("source_event_ref") != row.event_id
            ):
                contradictions.append("permission_disable_receipt_does_not_match_control_event")
        if disabled and restored and disabled.state == restored.state == "satisfied":
            left, right = disabled.fields, restored.fields
            if left.get("account_id_masked") != right.get("account_id_masked"):
                contradictions.append("permission_change_account_identity_mismatch")
            if left.get("change_id") != right.get("change_id"):
                contradictions.append("permission_change_id_mismatch")
            disabled_time = _parse_utc(str(left.get("occurred_at_utc", "")))
            restored_time = _parse_utc(str(right.get("occurred_at_utc", "")))
            if disabled_time is not None and restored_time is not None:
                if restored_time <= disabled_time:
                    contradictions.append("permission_restore_did_not_follow_disable")
                else:
                    if len(rows) == 1 and _parse_utc(rows[0].occurred_at_utc) != disabled_time:
                        contradictions.append("permission_disable_event_time_mismatch")
                    relevant_rows = [
                        row
                        for row in evidence.scenario_evidence
                        if row.event_kind == "order_reject_remote"
                        and row.fields.get("verified_rejection_class")
                        == "account_permission_denied"
                    ]
                    if len(relevant_rows) != 1:
                        missing.append("permission_rejection_requires_one_correlated_provider_event")
                    else:
                        reject_row = relevant_rows[0]
                        order_ref = reject_row.fields.get("order_ref")
                        requests = [
                            request
                            for request in evidence.managed_requests
                            if request.action is RequestAction.SUBMIT
                            and request.dispatch_state is DispatchState.DISPATCHED
                            and request.order_refs == (order_ref,)
                        ]
                        matching_facts = [
                            fact
                            for fact in evidence.order_facts
                            if fact.fact is NativeOrderFactKind.REJECTED
                            and fact.order_ref == order_ref
                            and fact.error_id == reject_row.fields.get("ErrorID")
                            and _parse_utc(fact.occurred_at_utc)
                            == _parse_utc(reject_row.occurred_at_utc)
                        ]
                        if len(requests) != 1 or len(matching_facts) != 1:
                            missing.append("permission_rejection_requires_one_managed_submit_and_native_fact")
                        else:
                            baseline, final = _snapshots_by_phase(evidence.snapshots)
                            request, fact = requests[0], matching_facts[0]
                            submit_rows = [
                                row
                                for row in evidence.scenario_evidence
                                if row.event_kind == "order_submit_request"
                                and row.fields.get("order_ref") == order_ref
                            ]
                            if len(submit_rows) != 1:
                                missing.append("permission_rejection_requires_one_submit_scenario_row")
                            else:
                                submit_row = submit_rows[0]
                                if (
                                    submit_row.fields.get("request_id") != request.request_id
                                    or submit_row.fields.get("request_generation")
                                    != request.request_generation
                                    or not isinstance(request.request_generation, int)
                                    or isinstance(request.request_generation, bool)
                                    or request.request_generation < 1
                                    or submit_row.fields.get("dispatch_state") != "dispatched"
                                    or submit_row.fields.get("account_id_masked")
                                    != request.account_id_masked
                                    or submit_row.fields.get("provider_session_id")
                                    != request.provider_session_id
                                    or submit_row.fields.get("trading_day") != request.trading_day
                                    or submit_row.source_sequence != request.sequence
                                    or _parse_utc(submit_row.occurred_at_utc)
                                    != _parse_utc(request.occurred_at_utc)
                                    or submit_row.evidence_sha256 != request.evidence_sha256
                                ):
                                    contradictions.append(
                                        "permission_submit_scenario_row_does_not_match_managed_receipt"
                                    )
                            disabled_row_error = rows[0].fields.get("ErrorID") if len(rows) == 1 else None
                            rejection_error = reject_row.fields.get("ErrorID")
                            if rows and (
                                rows[0].fields.get("blocked_order_ref") != order_ref
                                or not isinstance(disabled_row_error, int)
                                or isinstance(disabled_row_error, bool)
                                or not isinstance(rejection_error, int)
                                or isinstance(rejection_error, bool)
                                or disabled_row_error != rejection_error
                                or rejection_error != fact.error_id
                            ):
                                contradictions.append(
                                    "permission_control_error_and_blocked_ref_must_match_native_rejection"
                                )
                            request_time = _parse_utc(request.occurred_at_utc)
                            reject_row_time = _parse_utc(reject_row.occurred_at_utc)
                            fact_time = _parse_utc(fact.occurred_at_utc)
                            account_id = left.get("account_id_masked")
                            if not baseline.account_id_masked or not final.account_id_masked:
                                missing.append("permission_rejection_requires_account_identity_on_snapshots")
                            elif baseline.account_id_masked != final.account_id_masked:
                                contradictions.append("permission_account_identity_changed_between_snapshots")
                            if (
                                not request.account_id_masked
                                or request.account_id_masked != account_id
                                or request.account_id_masked != baseline.account_id_masked
                                or request.account_id_masked != final.account_id_masked
                            ):
                                contradictions.append("permission_submit_account_identity_mismatch")
                            if (
                                not fact.account_id_masked
                                or fact.account_id_masked != request.account_id_masked
                                or fact.account_id_masked != baseline.account_id_masked
                                or fact.account_id_masked != final.account_id_masked
                            ):
                                contradictions.append("permission_native_rejection_account_mismatch")
                            if (
                                not request.provider_session_id
                                or request.provider_session_id != fact.session_id
                                or fact.session_id != baseline.session_id
                                or fact.session_id != final.session_id
                                or reject_row.provider_session_id != fact.session_id
                                or rows[0].provider_session_id != baseline.session_id
                            ):
                                contradictions.append("permission_submit_provider_session_mismatch")
                            if (
                                not request.trading_day
                                or request.trading_day != fact.trading_day
                                or fact.trading_day != baseline.trading_day
                                or fact.trading_day != final.trading_day
                                or reject_row.trading_day != fact.trading_day
                                or rows[0].trading_day != baseline.trading_day
                            ):
                                contradictions.append("permission_submit_trading_day_mismatch")
                            for dependency in (disabled, restored):
                                if dependency is not None and dependency.state == "satisfied":
                                    if (
                                        dependency.fields.get("account_id_masked")
                                        != baseline.account_id_masked
                                        or dependency.fields.get("provider_session_id")
                                        != baseline.session_id
                                        or dependency.fields.get("trading_day")
                                        != baseline.trading_day
                                    ):
                                        contradictions.append(
                                            "permission_control_receipt_account_session_day_mismatch"
                                        )
                            if request_time is None or reject_row_time is None or fact_time is None:
                                missing.append("permission_rejection_requires_utc_event_timeline")
                            else:
                                if not disabled_time < request_time <= reject_row_time < restored_time:
                                    contradictions.append("permission_submit_and_rejection_must_occur_while_disabled")
                                if reject_row_time != fact_time:
                                    contradictions.append("permission_rejection_event_time_mismatch")
    if evidence.case_id == "EM02":
        pause = by_id.get("strategy_pause_authorized")
        rows = [
            row for row in evidence.scenario_evidence if row.event_kind == "strategy_trading_paused"
        ]
        if pause and pause.state == "satisfied" and len(rows) == 1:
            row = rows[0]
            if (
                pause.fields.get("strategy_id") != row.fields.get("strategy_id")
                or pause.fields.get("pause_event_ref") != row.event_id
            ):
                contradictions.append("strategy_pause_receipt_does_not_match_pause_event")
    if evidence.case_id == "EM03":
        logout = by_id.get("gateway_force_logout_ack")
        rows = [
            row
            for row in evidence.scenario_evidence
            if row.event_kind == "gateway_force_logout_requested"
        ]
        if logout and logout.state == "satisfied" and len(rows) == 1:
            row = rows[0]
            if (
                logout.fields.get("gateway_key") != row.fields.get("gateway_key")
                or logout.fields.get("session_id") != row.provider_session_id
                or logout.fields.get("source_event_ref") != row.event_id
            ):
                contradictions.append("force_logout_receipt_does_not_match_disconnect_event")


def _validate_native_identity(
    *,
    event_id: str,
    source: str,
    session_id: str,
    trading_day: str,
    sequence: int,
    occurred_at_utc: str,
    evidence_sha256: str,
) -> None:
    if source != "ctp_provider_callback":
        raise CompletionEvidenceError("native facts must originate from provider callback adapter")
    if not event_id or not session_id or not trading_day:
        raise CompletionEvidenceError("native fact requires event/session/trading-day identity")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise CompletionEvidenceError("native fact requires positive source sequence")
    if _parse_utc(occurred_at_utc) is None:
        raise CompletionEvidenceError("native fact timestamp must carry UTC offset")
    if not _SHA256_RE.fullmatch(evidence_sha256):
        raise CompletionEvidenceError("native fact requires SHA-256 evidence digest")


def _same_scope(current: tuple[str, str] | None, observed: tuple[str, str]) -> tuple[str, str]:
    if current is not None and current != observed:
        raise CompletionEvidenceError(
            "one case completion bundle cannot mix provider sessions/days"
        )
    return observed


def _snapshots_by_phase(
    snapshots: tuple[AccountReconciliationSnapshot, ...],
) -> tuple[AccountReconciliationSnapshot, AccountReconciliationSnapshot]:
    by_phase = {snapshot.phase: snapshot for snapshot in snapshots}
    return by_phase[SnapshotPhase.BASELINE], by_phase[SnapshotPhase.FINAL]


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _bounded_contract_decimal(value: Decimal) -> bool:
    """Keep exact validation arithmetic within a finite CTP field-sized range."""
    parts = value.as_tuple()
    return len(parts.digits) <= 32 and -12 <= parts.exponent <= 12


def _decimal_mapping(values: Mapping[str, Any]) -> dict[str, Decimal] | None:
    result: dict[str, Decimal] = {}
    for key, value in values.items():
        parsed = _decimal(value)
        if parsed is None:
            return None
        result[str(key)] = parsed
    return result


def _parse_utc(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        return None
    return result.astimezone(timezone.utc)
