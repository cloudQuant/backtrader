"""Offline G6-S candidate for settlement readback attestation.

This module validates an injected terminal settlement query and the exact
selected SimNow scope. It makes no SDK/native/provider calls, registers no
runtime, and cannot authorize any write. A production SDK provenance adapter is
required; the injected verifier contract is not implemented here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol, Tuple

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ACCOUNT_RE = re.compile(r"^[0-9a-f]{16}$", re.ASCII)
_ATTESTATION_SEAL = object()
_REQUIRED_COUNTERS = (
    "authenticate", "login", "settlement_confirm", "order_insert", "order_action",
    "query_account", "query_positions", "query_orders", "query_trades",
    "query_instruments", "query_margin_rate", "query_commission_rate",
    "query_depth_market_data", "query_option_trade_cost",
    "query_option_commission_rate", "query_settlement_confirmation",
)
_WRITE_COUNTERS = ("settlement_confirm", "order_insert", "order_action")


class SettlementAttestationError(ValueError):
    """Redacted fail-closed rejection for this local evidence contract."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise SettlementAttestationError(reason)


def _digest(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") == value
    except (OverflowError, ValueError):
        return False


def _expected_account_fingerprints(broker_id: str, investor_id: str) -> Tuple[str, str]:
    short = hashlib.sha256((broker_id + ":" + investor_id).encode("utf-8")).hexdigest()[:16]
    return short, hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


def _canonical_query_value(value: Any) -> Any:
    """Match the SDK query-record digest normalization for supported values."""
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            if type(key) is not str:
                _reject("settlement_query_record_key_invalid")
            output[key] = _canonical_query_value(item)
        return {key: output[key] for key in sorted(output)}
    if isinstance(value, (list, tuple)):
        return [_canonical_query_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            return {"__nonfinite_float__": value.hex()}
        return value
    if type(value) in (str, int, bool) or value is None:
        return value
    return {"__unsupported_type__": type(value).__module__ + "." + type(value).__qualname__}


def _records_digest(records: Tuple[Any, ...]) -> str:
    encoded = json.dumps(
        _canonical_query_value(records),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _filters_digest(filters: Tuple[Tuple[str, str], ...]) -> str:
    encoded = json.dumps(
        [[key, value] for key, value in filters],
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SelectedSimNowScope:
    """Non-secret identity sealed by an explicit config and pair selection."""

    config_digest: str
    registration_digest: str
    front_pair_set_sha256: str
    selected_pair_index: int
    md_front: str
    td_front: str
    broker_id: str
    investor_id: str
    account_fingerprint: str
    account_fingerprint_sha256: str

    def __post_init__(self) -> None:
        if not all(
            _digest(value)
            for value in (
                self.config_digest,
                self.registration_digest,
                self.front_pair_set_sha256,
                self.account_fingerprint_sha256,
            )
        ):
            _reject("settlement_expected_scope_digest_invalid")
        if type(self.selected_pair_index) is not int or self.selected_pair_index < 0:
            _reject("settlement_selected_pair_index_invalid")
        for value in (self.md_front, self.td_front, self.broker_id, self.investor_id):
            if type(value) is not str or not value or value != value.strip():
                _reject("settlement_expected_scope_text_invalid")
        if not _ACCOUNT_RE.fullmatch(self.account_fingerprint or ""):
            _reject("settlement_expected_account_fingerprint_invalid")
        short, full = _expected_account_fingerprints(self.broker_id, self.investor_id)
        if self.account_fingerprint != short or self.account_fingerprint_sha256 != full:
            _reject("settlement_expected_account_binding_invalid")


@dataclass(frozen=True)
class CurrentTdSession:
    """Read-only session/front snapshot observed at query verification time."""

    issuer: object = field(repr=False, compare=False)
    config_digest: str = ""
    registration_digest: str = ""
    front_pair_set_sha256: str = ""
    selected_pair_index: int = -1
    md_front_configured: str = ""
    md_front_registered: str = ""
    md_front_connected: str = ""
    td_front_configured: str = ""
    td_front_registered: str = ""
    td_front_connected: str = ""
    broker_id: str = ""
    investor_id: str = ""
    account_fingerprint: str = ""
    account_fingerprint_sha256: str = ""
    connection_generation: int = 0
    trading_day: str = ""
    connected: bool = False
    read_only_ready: bool = False
    auto_settlement_confirm: bool = True
    execution_gate_armed: bool = True
    native_api_current: bool = False
    bound_identity_current: bool = False


@dataclass(frozen=True)
class SettlementQuerySource:
    """Source fields that an SDK-specific verifier must authenticate."""

    issuer: object = field(repr=False, compare=False)
    request_type: str
    request_id: int
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    broker_id: str
    investor_id: str
    request_filters: Tuple[Tuple[str, str], ...]
    explicit_request_filters: Tuple[str, ...]
    records_sha256: str


@dataclass(frozen=True)
class SettlementQueryEvidence:
    """One query result envelope and its same-issuer source provenance."""

    request_type: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    complete: bool
    is_last_seen: bool
    timed_out: bool
    unsupported: bool
    error_code: Any
    error_message: str
    submit_code: Any
    late_callback_count: int
    records: Tuple[Any, ...]
    source: SettlementQuerySource
    request_counts_before: Tuple[Tuple[str, int], ...]
    request_counts_after: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class VerifiedSettlementQueryProvenance:
    """Result from the injected SDK source/history verifier.

    The verifier must validate the SDK source seal, same-client issuer, current
    query-history object, record digest, terminal callback and freshness. A
    fake verifier only exercises this contract; it is not provider evidence.
    """

    issuer: object = field(repr=False, compare=False)
    request_type: str
    request_id: int
    source_sha256: str
    records_sha256: str
    request_filters_sha256: str
    source_seal_verified: bool
    current_history_matches: bool
    terminal_callback_verified: bool
    fresh: bool


class SettlementQueryProvenanceVerifier(Protocol):
    def verify_settlement_query(
        self,
        query: SettlementQueryEvidence,
        expected: SelectedSimNowScope,
        current: CurrentTdSession,
    ) -> VerifiedSettlementQueryProvenance:
        """Verify SDK-issued source against its current retained query history."""


@dataclass(frozen=True)
class CtpSimNowSettlementAttestation:
    """Readback observation, explicitly carrying no dispatch authority."""

    config_digest: str
    registration_digest: str
    front_pair_set_sha256: str
    selected_pair_index: int
    md_front: str
    td_front: str
    account_fingerprint_sha256: str
    account_fingerprint: str
    broker_id: str
    investor_id: str
    trading_day: str
    connection_generation: int
    query_request_id: int
    query_source_sha256: str
    query_records_sha256: str
    settlement_confirmation_observed: bool
    query_terminal_provenance_verified: bool
    local_contract_only: bool
    atomic_snapshot_verified: bool
    account_writer_fence_verified: bool
    execution_gate_armed: bool
    write_authority_granted: bool
    query_settlement_confirmation_calls: int
    settlement_confirm_write_calls: int
    order_insert_write_calls: int
    order_action_write_calls: int
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _ATTESTATION_SEAL:
            _reject("settlement_attestation_unissued")
        if (
            self.settlement_confirmation_observed is not True
            or self.query_terminal_provenance_verified is not True
            or self.local_contract_only is not True
            or self.atomic_snapshot_verified is not False
            or self.account_writer_fence_verified is not False
            or self.execution_gate_armed is not False
            or self.write_authority_granted is not False
            or self.query_settlement_confirmation_calls != 1
            or self.settlement_confirm_write_calls != 0
            or self.order_insert_write_calls != 0
            or self.order_action_write_calls != 0
        ):
            _reject("settlement_attestation_authority_shape_invalid")



def _validate_request_counts(query: SettlementQueryEvidence) -> None:
    before = query.request_counts_before
    after = query.request_counts_after
    parsed = []
    for snapshot in (before, after):
        if type(snapshot) is not tuple:
            _reject("settlement_request_counts_invalid")
        counts = {}
        for pair in snapshot:
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or type(pair[1]) is not int
                or pair[1] < 0
                or pair[0] in counts
            ):
                _reject("settlement_request_counts_invalid")
            counts[pair[0]] = pair[1]
        if not set(_REQUIRED_COUNTERS).issubset(counts):
            _reject("settlement_request_counts_missing")
        if any(name not in _REQUIRED_COUNTERS and count != 0 for name, count in counts.items()):
            _reject("settlement_unclassified_request_observed")
        parsed.append(counts)
    before_counts, after_counts = parsed
    if set(before_counts) != set(after_counts):
        _reject("settlement_request_counts_shape_changed")
    if before_counts["authenticate"] != 1 or before_counts["login"] != 1:
        _reject("settlement_readiness_attempt_not_fresh")
    if before_counts["query_settlement_confirmation"] != 0:
        _reject("settlement_query_count_mismatch")
    if after_counts["query_settlement_confirmation"] != 1:
        _reject("settlement_query_count_mismatch")
    for name in _WRITE_COUNTERS:
        if before_counts[name] != 0 or after_counts[name] != 0:
            _reject("settlement_native_write_observed")
    for name in set(before_counts) - {"query_settlement_confirmation"}:
        if before_counts[name] != after_counts[name]:
            _reject("settlement_unexpected_request_observed")
def attest_simnow_settlement_readback(
    expected: SelectedSimNowScope,
    current: CurrentTdSession,
    query: SettlementQueryEvidence,
    *,
    provenance_verifier: SettlementQueryProvenanceVerifier,
) -> CtpSimNowSettlementAttestation:
    """Validate an injected current-day settlement query without doing IO.

    The function accepts only one exact account/day row from a terminal native
    query whose injected SDK verifier rechecks source provenance and retained
    query history. This local observation does not prove complete account
    coverage, a common snapshot, a writer fence, or any write authorization.
    """
    if type(expected) is not SelectedSimNowScope:
        _reject("settlement_expected_scope_required")
    if type(current) is not CurrentTdSession or current.issuer is None:
        _reject("settlement_current_session_required")
    if type(query) is not SettlementQueryEvidence or type(query.records) is not tuple:
        _reject("settlement_query_evidence_required")
    _validate_request_counts(query)
    if not callable(getattr(provenance_verifier, "verify_settlement_query", None)):
        _reject("settlement_query_provenance_verifier_required")

    short, full = _expected_account_fingerprints(expected.broker_id, expected.investor_id)
    if (
        current.config_digest != expected.config_digest
        or current.registration_digest != expected.registration_digest
        or current.front_pair_set_sha256 != expected.front_pair_set_sha256
        or current.selected_pair_index != expected.selected_pair_index
        or current.md_front_configured != expected.md_front
        or current.md_front_registered != expected.md_front
        or current.md_front_connected != expected.md_front
        or current.td_front_configured != expected.td_front
        or current.td_front_registered != expected.td_front
        or current.td_front_connected != expected.td_front
        or current.broker_id != expected.broker_id
        or current.investor_id != expected.investor_id
        or current.account_fingerprint != short
        or current.account_fingerprint_sha256 != full
        or type(current.connection_generation) is not int
        or current.connection_generation <= 0
        or not _day(current.trading_day)
        or current.connected is not True
        or current.read_only_ready is not True
        or current.auto_settlement_confirm is not False
        or current.execution_gate_armed is not False
        or current.native_api_current is not True
        or current.bound_identity_current is not True
    ):
        _reject("settlement_current_session_scope_mismatch")

    if (
        query.request_type != "settlement_confirmation"
        or type(query.request_id) is not int
        or query.request_id <= 0
        or type(query.connection_generation) is not int
        or query.connection_generation != current.connection_generation
        or query.account_fingerprint != current.account_fingerprint
        or query.complete is not True
        or query.is_last_seen is not True
        or query.timed_out is not False
        or query.unsupported is not False
        or query.error_code not in (None, 0)
        or query.error_message != ""
        or query.submit_code not in (None, 0)
        or type(query.late_callback_count) is not int
        or query.late_callback_count != 0
    ):
        _reject("settlement_query_not_terminal")

    source = query.source
    expected_filters = (("BrokerID", expected.broker_id), ("InvestorID", expected.investor_id))
    records_sha256 = _records_digest(query.records)
    if (
        type(source) is not SettlementQuerySource
        or source.issuer is not current.issuer
        or source.request_type != query.request_type
        or source.request_id != query.request_id
        or source.account_fingerprint != current.account_fingerprint
        or source.connection_generation != current.connection_generation
        or source.trading_day != current.trading_day
        or source.broker_id != expected.broker_id
        or source.investor_id != expected.investor_id
        or source.request_filters != expected_filters
        or source.explicit_request_filters != ()
        or source.records_sha256 != records_sha256
    ):
        _reject("settlement_query_source_scope_mismatch")

    if len(query.records) != 1:
        _reject("settlement_confirmation_row_count_invalid")
    row = query.records[0]
    if not isinstance(row, Mapping):
        _reject("settlement_confirmation_row_invalid")
    broker = row.get("BrokerID")
    investor = row.get("InvestorID")
    row_days = tuple(
        value for value in (row.get("TradingDay"), row.get("ConfirmDate"))
        if value not in (None, "")
    )
    if (
        type(broker) is not str
        or broker != expected.broker_id
        or type(investor) is not str
        or investor != expected.investor_id
        or not row_days
        or any(type(value) is not str or value != current.trading_day for value in row_days)
    ):
        _reject("settlement_confirmation_row_identity_mismatch")

    try:
        verified = provenance_verifier.verify_settlement_query(query, expected, current)
    except Exception:
        _reject("settlement_query_provenance_unavailable")
    if type(verified) is not VerifiedSettlementQueryProvenance:
        _reject("settlement_query_provenance_unverified")
    request_filters_sha256 = _filters_digest(expected_filters)
    if (
        type(verified.request_type) is not str
        or type(verified.request_id) is not int
        or verified.request_id <= 0
        or verified.issuer is not current.issuer
        or verified.request_type != query.request_type
        or verified.request_id != query.request_id
        or not _digest(verified.source_sha256)
        or verified.records_sha256 != records_sha256
        or verified.request_filters_sha256 != request_filters_sha256
        or verified.source_seal_verified is not True
        or verified.current_history_matches is not True
        or verified.terminal_callback_verified is not True
        or verified.fresh is not True
    ):
        _reject("settlement_query_provenance_mismatch")
    if _records_digest(query.records) != records_sha256:
        _reject("settlement_query_records_mutated_during_verification")

    return CtpSimNowSettlementAttestation(
        config_digest=expected.config_digest,
        registration_digest=expected.registration_digest,
        front_pair_set_sha256=expected.front_pair_set_sha256,
        selected_pair_index=expected.selected_pair_index,
        md_front=expected.md_front,
        td_front=expected.td_front,
        account_fingerprint_sha256=expected.account_fingerprint_sha256,
        account_fingerprint=expected.account_fingerprint,
        broker_id=expected.broker_id,
        investor_id=expected.investor_id,
        trading_day=current.trading_day,
        connection_generation=current.connection_generation,
        query_request_id=query.request_id,
        query_source_sha256=verified.source_sha256,
        query_records_sha256=records_sha256,
        settlement_confirmation_observed=True,
        query_terminal_provenance_verified=True,
        local_contract_only=True,
        atomic_snapshot_verified=False,
        account_writer_fence_verified=False,
        execution_gate_armed=False,
        write_authority_granted=False,
        query_settlement_confirmation_calls=1,
        settlement_confirm_write_calls=0,
        order_insert_write_calls=0,
        order_action_write_calls=0,
        _seal=_ATTESTATION_SEAL,
    )


__all__ = [
    "CtpSimNowSettlementAttestation",
    "CurrentTdSession",
    "SelectedSimNowScope",
    "SettlementAttestationError",
    "SettlementQueryEvidence",
    "SettlementQueryProvenanceVerifier",
    "SettlementQuerySource",
    "VerifiedSettlementQueryProvenance",
    "attest_simnow_settlement_readback",
]

