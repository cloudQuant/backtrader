"""Non-authorizing, one-shot SimNow TD settlement-readiness observation.

This module is deliberately unregistered. Call it only during controlled
startup, after ``start_ctp_simnow_native_readiness`` returned for the same
client, selected pair, account, and sealed config. It uses the public
``TraderClient.verify_settlement_confirmation`` query surface. That SDK method
does not call the native settlement-confirmation write; it queries the
provider's current confirmation record. Before this consumer returns
``td_trading_ready=True``, an explicitly injected verifier must build the
current, source-sealed settlement evidence from the SDK's terminal query
history and match it to the selected account, day, and connection generation.

The resulting object records that observation. It grants no order authority,
does not configure or arm the SDK execution gate, and is not registered in the
runtime inventory. Failure closes through the shared TD/MD resource owner. Its
callback is required because the prior readiness stage leaves both native
clients open; stopping only TD cannot prove the market client also closed. The
response must contain exactly one matching account/day row. Extra or ambiguous
rows fail closed.

The SDK bounds its callback wait with the supplied query timeout. Its native
query submission and any SDK query-throttle sleep are synchronous calls with
no hard wall-clock bound, so this adapter cannot promise a total startup
deadline around them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .ctp_native_shutdown import stop_ctp_native_client
from .ctp_sdk_artifact_binding import (
    CtpSdkArtifactBindingError,
    _get_preclient_code_owned_verifier,
    _load_code_owned_settlement_verifier,
    _require_exact_evidence_type,
)
from .ctp_simnow_managed_operator import CtpSimNowManagedScopeSelection
from .ctp_simnow_managed_runtime import (
    CtpSimNowNativeReadiness,
    CtpSimulationExecutionError,
)
from .ctp_simulation_execution import CtpSimulationExecutionRegistration

_REQUEST_COUNTERS = frozenset(
    (
        "authenticate",
        "login",
        "settlement_confirm",
        "order_insert",
        "order_action",
        "query_account",
        "query_positions",
        "query_orders",
        "query_trades",
        "query_instruments",
        "query_margin_rate",
        "query_commission_rate",
        "query_depth_market_data",
        "query_option_trade_cost",
        "query_option_commission_rate",
        "query_settlement_confirmation",
    )
)
_WRITE_COUNTERS = ("settlement_confirm", "order_insert", "order_action")
_SETTLEMENT_EVIDENCE_SCHEMA = "ctp_settlement_confirmation_evidence.v1"
_SETTLEMENT_EVIDENCE_TYPE_MODULE = (
    "bt_api_ctp.containers.ctp.ctp_native_query_certificate"
)
_SUPPORTED_SETTLEMENT_SOURCE_MANIFEST_SHA256 = (
    "da9d20d35d0b5680267f1a95c5b7fff54f25e9f57f0dfda270b55eb7f251ebe9"
)


class CtpSettlementSdkEvidence(Protocol):
    """Narrow typed surface of the SDK's sealed settlement evidence object."""

    @property
    def evidence_sha256(self) -> str: ...

    @property
    def expires_at_monotonic(self) -> float: ...

    def as_public_dict(self) -> dict[str, Any]: ...


class CtpSettlementEvidenceVerifier(Protocol):
    """Trusted integration seam for the exact SDK settlement evidence builder.

    A production composition must inject an adapter pinned to the SDK source
    manifest above. The adapter must call the SDK's current-history builder;
    this module intentionally has no SDK import or default adapter.
    """

    @property
    def source_manifest_sha256(self) -> str: ...

    @property
    def evidence_type(self) -> type[Any]: ...

    def verify_current(
        self, trader_client: Any, result: Any
    ) -> CtpSettlementSdkEvidence: ...


class CtpSimNowTdTradingReadinessError(CtpSimulationExecutionError):
    """Redacted failure while checking current TD settlement readiness."""

    def __init__(self, reason: str, *, close_state: str = "not_started") -> None:
        self.close_state = close_state
        super().__init__(reason)


@dataclass(frozen=True)
class CtpSimNowTdTradingReadinessConfig:
    """Non-secret startup identity used to bind the public TD observation."""

    md_front: str
    td_front: str
    broker_id: str
    user_id: str


@dataclass(frozen=True)
class CtpSimNowTdTradingReadiness:
    """Current server-readback observation; it carries no write authority."""

    config_digest: str
    registration_digest: str
    front_pair_set_sha256: str
    account_fingerprint_sha256: str
    account_fingerprint: str
    md_front: str
    td_front: str
    connection_generation: int
    trading_day: str
    settlement_query_request_id: int
    settlement_evidence_sha256: str
    settlement_callback_history_sha256: str
    settlement_sdk_source_manifest_sha256: str
    settlement_proof_source: str = "confirmation_query"
    settlement_readback_verified: bool = True
    td_trading_ready: bool = True
    md_ready: bool = True
    execution_gate_armed: bool = False
    write_authority_granted: bool = False


def _reject(reason: str) -> None:
    raise CtpSimNowTdTradingReadinessError(reason)


def _account_fingerprints(broker_id: str, user_id: str) -> tuple[str, str]:
    short = hashlib.sha256("{0}:{1}".format(broker_id, user_id).encode("utf-8")).hexdigest()[:16]
    return short, hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


def _valid_day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        time.strptime(value, "%Y%m%d")
    except (OverflowError, ValueError):
        return False
    return True


def _read_public_state(client: Any) -> tuple[dict[str, Any], dict[str, Any], Any]:
    try:
        state = client.get_session_state()
        front = client.get_front_binding_state()
        scope = client.get_query_session_scope()
    except Exception:
        _reject("managed_simnow_td_state_unavailable")
    if type(state) is not dict or type(front) is not dict:
        _reject("managed_simnow_td_state_unavailable")
    return state, front, scope


def _read_counts(client: Any) -> dict[str, int]:
    getter = getattr(client, "get_request_counts", None)
    if not callable(getter):
        _reject("managed_simnow_td_request_counts_unavailable")
    try:
        counts = getter()
    except Exception:
        _reject("managed_simnow_td_request_counts_unavailable")
    if type(counts) is not dict or not _REQUEST_COUNTERS.issubset(counts):
        _reject("managed_simnow_td_request_counts_unavailable")
    for key, value in counts.items():
        if type(key) is not str or type(value) is not int or value < 0:
            _reject("managed_simnow_td_request_counts_invalid")
        # Unknown future counters may be added by the SDK. A nonzero unknown
        # counter is ambiguous, so this strict startup adapter fails closed.
        if key not in _REQUEST_COUNTERS and value != 0:
            _reject("managed_simnow_td_unclassified_request_observed")
    return counts


def _validate_selection(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowTdTradingReadinessConfig,
    native_readiness: CtpSimNowNativeReadiness,
    timeout_seconds: float,
) -> CtpSimulationExecutionRegistration:
    if type(selection) is not CtpSimNowManagedScopeSelection:
        _reject("managed_simnow_selection_required")
    registration = selection.execution_registration
    if type(registration) is not CtpSimulationExecutionRegistration:
        _reject("managed_simnow_registration_required")
    if type(config) is not CtpSimNowTdTradingReadinessConfig:
        _reject("managed_simnow_td_config_required")
    if type(native_readiness) is not CtpSimNowNativeReadiness:
        _reject("managed_simnow_prior_native_readiness_required")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 60
    ):
        _reject("managed_simnow_td_timeout_invalid")
    identity_values = (config.md_front, config.td_front, config.broker_id, config.user_id)
    if any(
        type(value) is not str or not value or value != value.strip() for value in identity_values
    ):
        _reject("managed_simnow_td_config_invalid")
    if (
        registration.environment != "simnow"
        or registration.sdk_profile != "config_front_pair"
        or registration.config_digest != selection.config_digest
        or registration.front_pair_set_sha256 != selection.front_pair_set_sha256
        or registration.effective_digest != selection.effective_digest
        or registration.md_front != selection.front_pair_selection.pair.md_front
        or registration.td_front != selection.front_pair_selection.pair.td_front
        or config.md_front != registration.md_front
        or config.td_front != registration.td_front
    ):
        _reject("managed_simnow_td_selected_scope_mismatch")
    if (
        native_readiness.config_digest != selection.config_digest
        or native_readiness.registration_digest != registration.digest
        or native_readiness.account_fingerprint_sha256 != registration.account_fingerprint_sha256
        or native_readiness.md_front != registration.md_front
        or native_readiness.td_front != registration.td_front
        or native_readiness.td_ready is not True
        or native_readiness.md_ready is not True
        or native_readiness.td_trading_ready is not False
    ):
        _reject("managed_simnow_td_prior_readiness_scope_mismatch")
    _, account_digest = _account_fingerprints(config.broker_id, config.user_id)
    if not hmac.compare_digest(account_digest, registration.account_fingerprint_sha256):
        _reject("managed_simnow_td_account_mismatch")
    for name in (
        "get_session_state",
        "get_front_binding_state",
        "get_query_session_scope",
        "get_request_counts",
        "verify_settlement_confirmation",
        "stop",
    ):
        if not callable(getattr(trader_client, name, None)):
            _reject("managed_simnow_td_public_api_unavailable")
    return registration


def _validate_logged_in_session(
    state: dict[str, Any],
    front: dict[str, Any],
    scope: Any,
    config: CtpSimNowTdTradingReadinessConfig,
    registration: CtpSimulationExecutionRegistration,
    *,
    before_query: bool,
) -> tuple[int, str, str]:
    short_account, account_digest = _account_fingerprints(config.broker_id, config.user_id)
    generation = getattr(scope, "connection_generation", None)
    day = getattr(scope, "trading_day", None)
    gate_armed = state.get("execution_gate_armed")
    if (
        scope is None
        or getattr(scope, "read_only_ready", None) is not True
        or getattr(scope, "broker_id", None) != config.broker_id
        or getattr(scope, "investor_id", None) != config.user_id
        or getattr(scope, "account_fingerprint", None) != short_account
        or type(generation) is not int
        or generation != 1
        or not _valid_day(day)
        or state.get("connected") is not True
        or state.get("read_only_ready") is not True
        or state.get("account_fingerprint") != short_account
        or state.get("connection_generation") != generation
        or state.get("trading_day") != day
        or state.get("login_state") != "logged_in"
        or state.get("auth_state") != "authenticated"
        or state.get("auto_settlement_confirm") is not False
        or front.get("configured_front") != registration.td_front
        or front.get("registered_front") != registration.td_front
        or front.get("connection_confirmed_front") != registration.td_front
        or front.get("connected") is not True
        or front.get("native_api_current") is not True
        or front.get("bound_identity_current") is not True
        or front.get("connection_generation") != generation
        or gate_armed is not False
        or account_digest != registration.account_fingerprint_sha256
    ):
        _reject("managed_simnow_td_identity_or_generation_mismatch")

    if before_query:
        if (
            state.get("trading_ready") is not False
            or state.get("settlement_state") != "not_requested"
            or state.get("settlement_readback_verified") is not False
            or state.get("settlement_proof_source") != "none"
            or state.get("last_error") != {}
        ):
            _reject("managed_simnow_td_not_in_controlled_startup_state")
    else:
        if (
            state.get("trading_ready") is not True
            or state.get("settlement_state") != "confirmed"
            or state.get("settlement_readback_verified") is not True
            or state.get("settlement_proof_source") != "confirmation_query"
            or state.get("settlement_connection_generation") != generation
            or state.get("settlement_account_fingerprint") != short_account
            or state.get("settlement_trading_day") != day
        ):
            _reject("managed_simnow_td_settlement_readback_mismatch")
    return generation, day, short_account


def _record_value(record: Any, name: str) -> Any:
    if type(record) is dict:
        return record.get(name)
    try:
        return getattr(record, name)
    except Exception:
        return None


def _canonical_digest(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _parse_aware_datetime(value: Any) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _validate_sdk_settlement_evidence(
    trader_client: Any,
    result: Any,
    verifier: CtpSettlementEvidenceVerifier | None,
    *,
    request_id: int,
    generation: int,
    day: str,
    short_account: str,
    config: CtpSimNowTdTradingReadinessConfig,
) -> tuple[str, str]:
    _validate_evidence_verifier(verifier)
    source_manifest = getattr(verifier, "source_manifest_sha256", None)
    if (
        type(source_manifest) is not str
        or not hmac.compare_digest(
            source_manifest, _SUPPORTED_SETTLEMENT_SOURCE_MANIFEST_SHA256
        )
    ):
        _reject("managed_simnow_td_settlement_evidence_source_mismatch")
    build_current = getattr(verifier, "verify_current", None)
    if not callable(build_current):
        _reject("managed_simnow_td_settlement_evidence_verifier_invalid")
    try:
        evidence = build_current(trader_client, result)
        expected_evidence_type = getattr(verifier, "evidence_type", None)
        try:
            _require_exact_evidence_type(evidence, expected_evidence_type)
        except CtpSdkArtifactBindingError:
            _reject("managed_simnow_td_settlement_evidence_type_invalid")
        public_getter = getattr(evidence, "as_public_dict", None)
        if not callable(public_getter):
            _reject("managed_simnow_td_settlement_evidence_untrusted")
        public = public_getter()
        evidence_digest = getattr(evidence, "evidence_sha256", None)
        expires_at_monotonic = getattr(evidence, "expires_at_monotonic", None)
    except CtpSimNowTdTradingReadinessError:
        raise
    except Exception:
        _reject("managed_simnow_td_settlement_evidence_verification_failed")
    required = {
        "schema",
        "request_type",
        "request_id",
        "complete",
        "is_last_seen",
        "timed_out",
        "unsupported",
        "error_code",
        "submit_code",
        "late_callback_count",
        "account_fingerprint_sha256",
        "broker_id_sha256",
        "investor_id_sha256",
        "connection_generation",
        "trading_day",
        "request_filter_names",
        "request_filters_sha256",
        "terminal_callback_records_sha256",
        "terminal_callback_history_sha256",
        "record_count",
        "confirmed_date",
        "started_at_utc",
        "completed_at_utc",
        "expires_at_utc",
        "execution_authorized",
        "evidence_sha256",
    }
    if type(public) is not dict or set(public) != required:
        _reject("managed_simnow_td_settlement_evidence_shape_invalid")
    if (
        type(evidence_digest) is not str
        or type(public["evidence_sha256"]) is not str
        or not _valid_sha256(evidence_digest)
        or not _valid_sha256(public["evidence_sha256"])
    ):
        _reject("managed_simnow_td_settlement_evidence_digest_invalid")
    payload = {key: value for key, value in public.items() if key not in {
        "execution_authorized", "evidence_sha256"
    }}
    if (
        not hmac.compare_digest(evidence_digest, public["evidence_sha256"])
        or not hmac.compare_digest(_canonical_digest(payload), evidence_digest)
    ):
        _reject("managed_simnow_td_settlement_evidence_digest_mismatch")
    if (
        public["schema"] != _SETTLEMENT_EVIDENCE_SCHEMA
        or type(public["schema"]) is not str
        or public["request_type"] != "settlement_confirmation"
        or type(public["request_type"]) is not str
        or type(public["request_id"]) is not int
        or public["request_id"] != request_id
        or public["complete"] is not True
        or public["is_last_seen"] is not True
        or public["timed_out"] is not False
        or public["unsupported"] is not False
        or public["error_code"] not in (None, 0)
        or (public["error_code"] is not None and type(public["error_code"]) is not int)
        or public["submit_code"] not in (None, 0)
        or (public["submit_code"] is not None and type(public["submit_code"]) is not int)
        or type(public["late_callback_count"]) is not int
        or public["late_callback_count"] != 0
        or public["connection_generation"] != generation
        or type(public["connection_generation"]) is not int
        or type(public["trading_day"]) is not str
        or public["trading_day"] != day
        or type(public["confirmed_date"]) is not str
        or public["confirmed_date"] != day
        or public["request_filter_names"] != ["BrokerID", "InvestorID"]
        or public["record_count"] != 1
        or type(public["record_count"]) is not int
        or public["execution_authorized"] is not False
    ):
        _reject("managed_simnow_td_settlement_evidence_identity_mismatch")
    expected_hashes = {
        "account_fingerprint_sha256": hashlib.sha256(short_account.encode("utf-8")).hexdigest(),
        "broker_id_sha256": hashlib.sha256(config.broker_id.encode("utf-8")).hexdigest(),
        "investor_id_sha256": hashlib.sha256(config.user_id.encode("utf-8")).hexdigest(),
    }
    for field, expected in expected_hashes.items():
        actual = public[field]
        if type(actual) is not str or not hmac.compare_digest(actual, expected):
            _reject("managed_simnow_td_settlement_evidence_identity_mismatch")
    for field in (
        "request_filters_sha256",
        "terminal_callback_records_sha256",
        "terminal_callback_history_sha256",
        "evidence_sha256",
    ):
        if not _valid_sha256(public[field]):
            _reject("managed_simnow_td_settlement_evidence_digest_invalid")
    expected_filter_digest = _canonical_digest(
        {
            "filters": [["BrokerID", config.broker_id], ["InvestorID", config.user_id]],
            "explicit_filters": [],
        }
    )
    if not hmac.compare_digest(public["request_filters_sha256"], expected_filter_digest):
        _reject("managed_simnow_td_settlement_evidence_filter_mismatch")
    started = _parse_aware_datetime(public["started_at_utc"])
    completed = _parse_aware_datetime(public["completed_at_utc"])
    expires = _parse_aware_datetime(public["expires_at_utc"])
    now = datetime.now(timezone.utc)
    if (
        started is None
        or completed is None
        or expires is None
        or type(expires_at_monotonic) is not float
        or not math.isfinite(expires_at_monotonic)
        or time.monotonic() >= expires_at_monotonic
        or not started <= completed <= now < expires
    ):
        _reject("managed_simnow_td_settlement_evidence_stale")
    return public["evidence_sha256"], public["terminal_callback_history_sha256"]


def _validate_evidence_verifier(
    verifier: CtpSettlementEvidenceVerifier | None,
) -> None:
    if verifier is None:
        _reject("managed_simnow_td_settlement_evidence_verifier_required")
    source_manifest = getattr(verifier, "source_manifest_sha256", None)
    build_current = getattr(verifier, "verify_current", None)
    if (
        type(source_manifest) is not str
        or not hmac.compare_digest(
            source_manifest, _SUPPORTED_SETTLEMENT_SOURCE_MANIFEST_SHA256
        )
        or not callable(build_current)
    ):
        _reject("managed_simnow_td_settlement_evidence_source_mismatch")


def _validate_query_result(
    result: Any,
    *,
    generation: int,
    day: str,
    short_account: str,
    config: CtpSimNowTdTradingReadinessConfig,
) -> int:
    if (
        getattr(result, "request_type", None) != "settlement_confirmation"
        or getattr(result, "complete", None) is not True
        or getattr(result, "is_last_seen", None) is not True
        or getattr(result, "timed_out", None) is not False
        or getattr(result, "unsupported", None) is not False
        or getattr(result, "late_callback_count", None) != 0
        or getattr(result, "error_code", None) not in (None, 0)
        or getattr(result, "submit_code", None) not in (None, 0)
        or getattr(result, "connection_generation", None) != generation
        or getattr(result, "account_fingerprint", None) != short_account
    ):
        _reject("managed_simnow_td_settlement_query_incomplete")
    request_id = getattr(result, "request_id", None)
    records = getattr(result, "records", None)
    if (
        type(request_id) is not int
        or request_id <= 0
        or type(records) is not tuple
        or len(records) != 1
    ):
        _reject("managed_simnow_td_settlement_query_shape_invalid")
    record = records[0]
    broker = _record_value(record, "BrokerID")
    investor = _record_value(record, "InvestorID")
    confirmation_day = _record_value(record, "TradingDay") or _record_value(record, "ConfirmDate")
    if broker != config.broker_id or investor != config.user_id or confirmation_day != day:
        _reject("managed_simnow_td_settlement_record_identity_mismatch")
    return request_id


def _validate_counter_delta(before: dict[str, int], after: dict[str, int]) -> None:
    if set(before) != set(after):
        _reject("managed_simnow_td_request_counters_changed_shape")
    for name in _WRITE_COUNTERS:
        if before[name] != 0 or after[name] != 0:
            _reject("managed_simnow_td_write_request_observed")
    if before["query_settlement_confirmation"] != 0 or after["query_settlement_confirmation"] != 1:
        _reject("managed_simnow_td_settlement_query_count_mismatch")
    for name in set(before) - {"query_settlement_confirmation"}:
        if before[name] != after[name]:
            _reject("managed_simnow_td_unexpected_request_observed")


def _close_after_failure(trader_client: Any, failure_cleanup: Callable[[], None] | None) -> bool:
    if callable(failure_cleanup):
        try:
            failure_cleanup()
        except BaseException:
            # The owner already attempted every resource. Do not retry an
            # uncertain native stop after its close result is incomplete.
            return False
        return True
    stop_ctp_native_client(trader_client)
    # Only the owner callback can assert that both native clients were closed.
    return False


def _verify_ctp_simnow_td_trading_readiness_with_test_verifier(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowTdTradingReadinessConfig,
    *,
    native_readiness: CtpSimNowNativeReadiness,
    settlement_evidence_verifier: CtpSettlementEvidenceVerifier | None = None,
    failure_cleanup: Callable[[], None] | None = None,
    timeout_seconds: float = 5.0,
) -> CtpSimNowTdTradingReadiness:
    """Verify current settlement readback for one already logged-in SimNow TD.

    The only native request made by this function is the SDK's read-only
    ``ReqQrySettlementInfoConfirm`` query. The method must run once, directly
    after the matching TD/MD login-readiness stage and before any execution
    arming. An exact current SDK settlement evidence verifier is mandatory;
    any ambiguous, stale, or mismatched result closes the owned session.
    """

    try:
        if not callable(failure_cleanup):
            _reject("managed_simnow_td_failure_cleanup_required")
        _validate_evidence_verifier(settlement_evidence_verifier)
        registration = _validate_selection(
            trader_client,
            selection,
            config,
            native_readiness,
            timeout_seconds,
        )
        state_before, front_before, scope_before = _read_public_state(trader_client)
        generation, day, short_account = _validate_logged_in_session(
            state_before,
            front_before,
            scope_before,
            config,
            registration,
            before_query=True,
        )
        counts_before = _read_counts(trader_client)
        if (
            counts_before["authenticate"] != 1
            or counts_before["login"] != 1
            or any(counts_before[name] != 0 for name in _WRITE_COUNTERS)
            or counts_before["query_settlement_confirmation"] != 0
        ):
            _reject("managed_simnow_td_not_fresh_readiness_attempt")
        try:
            result = trader_client.verify_settlement_confirmation(timeout=float(timeout_seconds))
        except Exception:
            counts_after_query = _read_counts(trader_client)
            _validate_counter_delta(counts_before, counts_after_query)
            _reject("managed_simnow_td_settlement_query_failed")
        counts_after_query = _read_counts(trader_client)
        _validate_counter_delta(counts_before, counts_after_query)
        request_id = _validate_query_result(
            result,
            generation=generation,
            day=day,
            short_account=short_account,
            config=config,
        )
        evidence_sha256, history_sha256 = _validate_sdk_settlement_evidence(
            trader_client,
            result,
            settlement_evidence_verifier,
            request_id=request_id,
            generation=generation,
            day=day,
            short_account=short_account,
            config=config,
        )
        state_after, front_after, scope_after = _read_public_state(trader_client)
        final_generation, final_day, final_account = _validate_logged_in_session(
            state_after,
            front_after,
            scope_after,
            config,
            registration,
            before_query=False,
        )
        counts_after = _read_counts(trader_client)
        if counts_after != counts_after_query:
            _reject("managed_simnow_td_unexpected_request_observed")
        if (
            final_generation != generation
            or final_day != day
            or final_account != short_account
            or state_after.get("settlement_proof_query_request_id") != request_id
            or front_after != front_before
            or state_after.get("execution_gate_armed") is not False
        ):
            _reject("managed_simnow_td_final_scope_changed")
        return CtpSimNowTdTradingReadiness(
            config_digest=selection.config_digest,
            registration_digest=registration.digest,
            front_pair_set_sha256=selection.front_pair_set_sha256,
            account_fingerprint_sha256=registration.account_fingerprint_sha256,
            account_fingerprint=short_account,
            md_front=registration.md_front,
            td_front=registration.td_front,
            connection_generation=generation,
            trading_day=day,
            settlement_query_request_id=request_id,
            settlement_evidence_sha256=evidence_sha256,
            settlement_callback_history_sha256=history_sha256,
            settlement_sdk_source_manifest_sha256=_SUPPORTED_SETTLEMENT_SOURCE_MANIFEST_SHA256,
        )
    except CtpSimNowTdTradingReadinessError as exc:
        closed = _close_after_failure(trader_client, failure_cleanup)
        raise CtpSimNowTdTradingReadinessError(
            exc.reason,
            close_state="closed" if closed else "close_failed",
        ) from None
    except Exception:
        closed = _close_after_failure(trader_client, failure_cleanup)
        raise CtpSimNowTdTradingReadinessError(
            "managed_simnow_td_readiness_unavailable",
            close_state="closed" if closed else "close_failed",
        ) from None


def verify_ctp_simnow_td_trading_readiness(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowTdTradingReadinessConfig,
    *,
    native_readiness: CtpSimNowNativeReadiness,
    failure_cleanup: Callable[[], None] | None = None,
    timeout_seconds: float = 5.0,
) -> CtpSimNowTdTradingReadiness:
    """Production-shaped entrypoint; resolves only the code-owned SDK bridge.

    The caller cannot supply a verifier or artifact policy. Deployment code
    must call :func:`require_trusted_ctp_sdk_artifact_before_client` before
    constructing the SDK client; this entrypoint repeats the pin gate before
    touching the supplied client. No release pin is present in this candidate,
    so this route rejects before client methods, SDK imports, or native queries.
    """

    try:
        verifier = _get_preclient_code_owned_verifier()
    except CtpSdkArtifactBindingError as exc:
        raise CtpSimNowTdTradingReadinessError(exc.reason, close_state="not_started") from None
    return _verify_ctp_simnow_td_trading_readiness_with_test_verifier(
        trader_client,
        selection,
        config,
        native_readiness=native_readiness,
        settlement_evidence_verifier=verifier,
        failure_cleanup=failure_cleanup,
        timeout_seconds=timeout_seconds,
    )


def require_trusted_ctp_sdk_artifact_before_client() -> None:
    """Fail closed unless the code-owned SDK artifact pin is available.

    Call this before importing/constructing the SDK client or native API. The
    function intentionally accepts no verifier, module, root, or policy input.
    """

    _load_code_owned_settlement_verifier()
