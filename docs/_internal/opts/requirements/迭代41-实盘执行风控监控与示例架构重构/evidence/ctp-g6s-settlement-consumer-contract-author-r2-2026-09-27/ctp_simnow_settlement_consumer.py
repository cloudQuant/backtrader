"""Fail-closed consumer contract for current SimNow settlement evidence.

This isolated candidate is deliberately not registered or imported by the runtime
inventory/CLI. The attestor is an injected trust boundary; this module validates
the shape and exact binding it must provide but cannot establish a provider
origin. Every success in the accompanying tests is fake-only and non-authorizing.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from backtrader_runtime.ctp_simnow_managed_operator import CtpSimNowManagedScopeSelection
from backtrader_runtime.ctp_simnow_managed_runtime import CtpSimNowNativeReadiness

# Exact disposable G4-r2 settlement-overlay artifact from the frozen unified
# wheelhouse candidate. It is a probe identity, not an accepted production pin.
SDK_DISTRIBUTION = "bt_api_ctp"
SDK_VERSION = "2.0.4+g4r2.settlement.probe.20260927"
SDK_WHEEL_SHA256 = "857b06c914cfc4f58bc04a77f11b77ad5dc3c47dc2be4d9d18b8e2fc805b264d"
SDK_SOURCE_MANIFEST_SHA256 = "da9d20d35d0b5680267f1a95c5b7fff54f25e9f57f0dfda270b55eb7f251ebe9"
_CALLBACK = "OnRspQrySettlementInfoConfirm"
_FILTERS = ("BrokerID", "InvestorID")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class CtpSimNowSettlementConsumerRejected(ValueError):
    """Redacted rejection from the settlement evidence consumer contract."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpSimNowSettlementConsumerRejected(reason)


def _sha(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _valid_day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except (OverflowError, ValueError):
        return False
    return True


def _valid_zero_code(value: Any) -> bool:
    """Accept only the native zero sentinel or None, never bool-as-int."""
    return value is None or (type(value) is int and value == 0)


def _identifier_sha256(value: str) -> str:
    return hashlib.sha256(b"ctp-settlement-identifier-v1\0" + value.encode("utf-8")).hexdigest()


def _pair_sha256(md_front: str, td_front: str) -> str:
    payload = json.dumps([md_front, td_front], ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(b"ctp-simnow-selected-pair-v1\0" + payload).hexdigest()


def _sdk_pin_sha256() -> str:
    payload = {
        "distribution": SDK_DISTRIBUTION,
        "version": SDK_VERSION,
        "wheel_sha256": SDK_WHEEL_SHA256,
        "source_manifest_sha256": SDK_SOURCE_MANIFEST_SHA256,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(b"ctp-simnow-sdk-pin-v1\0" + encoded).hexdigest()


def _account_fingerprint_sha256(broker_id: str, investor_id: str) -> str:
    short = hashlib.sha256((broker_id + ":" + investor_id).encode("utf-8")).hexdigest()[:16]
    return hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class CtpSimNowSettlementExpectedScope:
    """Expected scope captured from the exact selected pair and current TD state."""

    selection: CtpSimNowManagedScopeSelection = field(repr=False)
    native_readiness: CtpSimNowNativeReadiness = field(repr=False)
    broker_id: str = field(repr=False)
    investor_id: str = field(repr=False)
    trading_day: str
    connection_generation: int

    def __post_init__(self) -> None:
        if type(self.selection) is not CtpSimNowManagedScopeSelection:
            _reject("settlement_selected_scope_required")
        if type(self.native_readiness) is not CtpSimNowNativeReadiness:
            _reject("settlement_native_readiness_required")
        registration = self.selection.execution_registration
        if (
            self.native_readiness.matches(self.selection) is not True
            or type(self.broker_id) is not str
            or not self.broker_id
            or type(self.investor_id) is not str
            or not self.investor_id
            or _account_fingerprint_sha256(self.broker_id, self.investor_id)
            != registration.account_fingerprint_sha256
            or not _valid_day(self.trading_day)
            or type(self.connection_generation) is not int
            or self.connection_generation <= 0
        ):
            _reject("settlement_expected_scope_invalid")

    @property
    def selected_pair_sha256(self) -> str:
        registration = self.selection.execution_registration
        return _pair_sha256(registration.md_front, registration.td_front)


@dataclass(frozen=True)
class CtpSimNowSettlementQueryAttestation:
    """Typed SDK-to-runtime contract; fields must originate from an attestor.

    Raw BrokerID/InvestorID filter values are repr-hidden. ConfirmDate is kept
    distinct from the SDK session TradingDay because the native settlement
    confirmation row has ConfirmDate but no TradingDay member.
    """

    sdk_distribution: str
    sdk_version: str
    sdk_wheel_sha256: str
    sdk_source_manifest_sha256: str
    sdk_pin_sha256: str
    selected_pair_sha256: str
    account_fingerprint_sha256: str
    request_type: str
    request_id: int
    complete: bool
    is_last_seen: bool
    timed_out: bool
    unsupported: bool
    error_code: int | None
    submit_code: int | None
    late_callback_count: int
    request_intent_filters: tuple[tuple[str, str], ...] = field(repr=False)
    request_filter_readback: tuple[tuple[str, str], ...] = field(repr=False)
    explicit_request_filters: tuple[str, ...]
    query_source_seal_sha256: str
    query_source_history_sha256: str
    callback_source: str
    terminal_callback_records_sha256: str
    terminal_callback_history_sha256: str
    query_trading_day: str
    query_connection_generation: int
    current_trading_day: str
    current_connection_generation: int
    current_account_fingerprint_sha256: str
    record_count: int
    row_broker_id_sha256: str
    row_investor_id_sha256: str
    confirm_date: str
    row_trading_day: str | None
    evidence_sha256: str


class CtpSimNowSettlementAttestor(Protocol):
    """Injected provider-facing contract. No implementation is trusted here."""

    def attest_current_settlement(
        self, expected: CtpSimNowSettlementExpectedScope
    ) -> CtpSimNowSettlementQueryAttestation: ...


@dataclass(frozen=True)
class CtpSimNowSettlementConsumerReceipt:
    """Shape-validation receipt; it never means provider trust or write authority."""

    selected_pair_sha256: str
    account_fingerprint_sha256: str
    trading_day: str
    connection_generation: int
    sdk_pin_sha256: str
    settlement_evidence_sha256: str
    consumer_contract_satisfied: bool = True
    provider_source_trusted: bool = False
    execution_authorized: bool = False


def _validate_attestation(
    evidence: CtpSimNowSettlementQueryAttestation,
    expected: CtpSimNowSettlementExpectedScope,
) -> None:
    registration = expected.selection.execution_registration
    exact_filters = (("BrokerID", expected.broker_id), ("InvestorID", expected.investor_id))
    required_digests = (
        evidence.sdk_wheel_sha256,
        evidence.sdk_source_manifest_sha256,
        evidence.sdk_pin_sha256,
        evidence.selected_pair_sha256,
        evidence.account_fingerprint_sha256,
        evidence.query_source_seal_sha256,
        evidence.query_source_history_sha256,
        evidence.terminal_callback_records_sha256,
        evidence.terminal_callback_history_sha256,
        evidence.current_account_fingerprint_sha256,
        evidence.row_broker_id_sha256,
        evidence.row_investor_id_sha256,
        evidence.evidence_sha256,
    )
    if any(not _sha(item) for item in required_digests):
        _reject("settlement_attestation_digest_missing_or_invalid")
    if (
        evidence.sdk_distribution != SDK_DISTRIBUTION
        or evidence.sdk_version != SDK_VERSION
        or evidence.sdk_wheel_sha256 != SDK_WHEEL_SHA256
        or evidence.sdk_source_manifest_sha256 != SDK_SOURCE_MANIFEST_SHA256
        or evidence.sdk_pin_sha256 != _sdk_pin_sha256()
    ):
        _reject("settlement_sdk_pin_mismatch")
    if (
        evidence.selected_pair_sha256 != expected.selected_pair_sha256
        or evidence.account_fingerprint_sha256 != registration.account_fingerprint_sha256
        or evidence.current_account_fingerprint_sha256 != registration.account_fingerprint_sha256
    ):
        _reject("settlement_selected_pair_or_account_mismatch")
    if (
        evidence.request_type != "settlement_confirmation"
        or type(evidence.request_id) is not int
        or evidence.request_id <= 0
        or evidence.complete is not True
        or evidence.is_last_seen is not True
        or evidence.timed_out is not False
        or evidence.unsupported is not False
        or not _valid_zero_code(evidence.error_code)
        or not _valid_zero_code(evidence.submit_code)
        or type(evidence.late_callback_count) is not int
        or evidence.late_callback_count != 0
    ):
        _reject("settlement_query_not_terminal")
    if (
        type(evidence.request_intent_filters) is not tuple
        or evidence.request_intent_filters != exact_filters
        or type(evidence.request_filter_readback) is not tuple
        or evidence.request_filter_readback != exact_filters
        or type(evidence.explicit_request_filters) is not tuple
        or evidence.explicit_request_filters != ()
    ):
        _reject("settlement_request_filter_readback_missing_or_mismatched")
    if evidence.callback_source != _CALLBACK:
        _reject("settlement_callback_source_missing_or_mismatched")
    if (
        not _valid_day(expected.trading_day)
        or evidence.query_trading_day != expected.trading_day
        or evidence.current_trading_day != expected.trading_day
        or not _valid_day(evidence.query_trading_day)
        or not _valid_day(evidence.current_trading_day)
        or type(evidence.query_connection_generation) is not int
        or evidence.query_connection_generation <= 0
        or evidence.query_connection_generation != expected.connection_generation
        or type(evidence.current_connection_generation) is not int
        or evidence.current_connection_generation <= 0
        or evidence.current_connection_generation != expected.connection_generation
    ):
        _reject("settlement_current_trading_day_or_generation_mismatch")
    if (
        type(evidence.record_count) is not int
        or evidence.record_count != 1
        or evidence.row_broker_id_sha256 != _identifier_sha256(expected.broker_id)
        or evidence.row_investor_id_sha256 != _identifier_sha256(expected.investor_id)
        or evidence.confirm_date != expected.trading_day
        or (evidence.row_trading_day is not None and evidence.row_trading_day != expected.trading_day)
    ):
        _reject("settlement_confirmation_row_scope_mismatch")


def consume_current_settlement_readiness(
    native_readiness: CtpSimNowNativeReadiness,
    expected: CtpSimNowSettlementExpectedScope,
    *,
    attestor: CtpSimNowSettlementAttestor | None = None,
) -> CtpSimNowSettlementConsumerReceipt:
    """Require one current, exact-pair settlement attestation or reject closed.

    This is an unregistered candidate consumer. It has no writer API, never
    selects another front pair, and only returns a non-authorizing shape receipt.
    Omitting the injected attestor is a hard refusal.
    """

    if type(native_readiness) is not CtpSimNowNativeReadiness or type(expected) is not CtpSimNowSettlementExpectedScope:
        _reject("settlement_native_readiness_and_scope_required")
    if native_readiness.matches(expected.selection) is not True or expected.native_readiness != native_readiness:
        _reject("settlement_native_readiness_scope_mismatch")
    if attestor is None or not callable(getattr(attestor, "attest_current_settlement", None)):
        _reject("settlement_attestor_required")
    try:
        evidence = attestor.attest_current_settlement(expected)
    except CtpSimNowSettlementConsumerRejected:
        raise
    except Exception as exc:
        raise CtpSimNowSettlementConsumerRejected("settlement_attestor_failed") from exc
    if type(evidence) is not CtpSimNowSettlementQueryAttestation:
        _reject("settlement_attestation_type_invalid")
    _validate_attestation(evidence, expected)
    return CtpSimNowSettlementConsumerReceipt(
        selected_pair_sha256=expected.selected_pair_sha256,
        account_fingerprint_sha256=expected.selection.execution_registration.account_fingerprint_sha256,
        trading_day=expected.trading_day,
        connection_generation=expected.connection_generation,
        sdk_pin_sha256=evidence.sdk_pin_sha256,
        settlement_evidence_sha256=evidence.evidence_sha256,
    )


__all__ = [
    "CtpSimNowSettlementAttestor",
    "CtpSimNowSettlementConsumerReceipt",
    "CtpSimNowSettlementConsumerRejected",
    "CtpSimNowSettlementExpectedScope",
    "CtpSimNowSettlementQueryAttestation",
    "consume_current_settlement_readiness",
]
