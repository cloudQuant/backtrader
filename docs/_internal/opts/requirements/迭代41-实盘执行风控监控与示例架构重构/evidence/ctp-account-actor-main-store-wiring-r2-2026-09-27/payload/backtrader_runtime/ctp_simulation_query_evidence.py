"""Fail-closed evidence adapter for unregistered SimNow managed recovery.

This adapter checks the native ``TraderClient`` query provenance retained by
``CtpTraderClientSimulationPort``.  It does not register a route, provide a
writer fence, establish an atomic multi-query snapshot, or recover durable
cancel history after a process restart.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .ctp_simulation_execution import (
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationOrderSnapshot,
    CtpSimulationPositionSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationSessionIdentity,
    CtpSimulationTradeSnapshot,
)

_ORDER_TARGET_OBSERVATION_SEAL = object()
_ORDER_TARGET_OBSERVATION_TTL_NS = 2_000_000_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SDK_ACCOUNT_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{16}$", re.ASCII)


def _reject(reason: str) -> None:
    raise CtpSimulationExecutionError(reason)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore").rstrip("\x00 ")
    if type(value) is str:
        return value.rstrip("\x00 ")
    return str(value).rstrip("\x00 ")


def _value(row: Any, *names: str) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if name in row:
                return row[name]
    for name in names:
        try:
            result = getattr(row, name, None)
        except Exception:
            return None
        if result is not None:
            return result
    return None


def _int(row: Any, *names: str, optional: bool = False) -> int:
    value = _value(row, *names)
    if optional and value in (None, ""):
        return 0
    if isinstance(value, bool):
        _reject("native_query_integer_invalid")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        _reject("native_query_integer_invalid")


def _decimal(row: Any, *names: str) -> Decimal:
    try:
        result = Decimal(str(_value(row, *names)))
    except (InvalidOperation, TypeError, ValueError):
        _reject("native_query_decimal_invalid")
    if not result.is_finite():
        _reject("native_query_decimal_invalid")
    return result


def _canonical_digest(domain: bytes, value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return hashlib.sha256(domain + encoded).hexdigest()


@dataclass(frozen=True)
class CtpSimulationOrderTargetObservation:
    """Short-lived query observation; it is not a cancel authorization.

    The opaque SDK issuer reference and module seal make accidental promotion
    from a caller-built row harder. They are only an in-process contract, not
    a security boundary. A future I9 issuer must still bind this observation
    to its durable reservation and same-store readback before any dispatch.
    """

    registration_digest: str
    reservation_digest: str
    request_digest: str
    source_digest: str
    request_id: int
    request_type: str
    account_fingerprint: str
    trading_day: str
    connection_generation: int
    order_ref: str
    order_sys_id: str
    exchange_id: str
    front_id: int
    session_id: int
    quantity: int
    traded_quantity: int
    remaining_quantity: int
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    expires_at_utc: datetime
    _seal: object = field(repr=False, compare=False)
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _ORDER_TARGET_OBSERVATION_SEAL:
            _reject("native_order_target_observation_unissued")
        for name in (
            "registration_digest",
            "reservation_digest",
            "request_digest",
            "source_digest",
        ):
            if type(getattr(self, name)) is not str or not _SHA256_RE.fullmatch(
                getattr(self, name)
            ):
                _reject("native_order_target_observation_digest_invalid")
        if (
            type(self.request_id) is not int
            or self.request_id <= 0
            or self.request_type != "orders"
            or type(self.account_fingerprint) is not str
            or not _SDK_ACCOUNT_FINGERPRINT_RE.fullmatch(self.account_fingerprint)
            or type(self.trading_day) is not str
            or len(self.trading_day) != 8
            or not self.trading_day.isascii()
            or not self.trading_day.isdigit()
            or type(self.connection_generation) is not int
            or self.connection_generation <= 0
            or type(self.order_ref) is not str
            or len(self.order_ref) != 12
            or not self.order_ref.isascii()
            or not self.order_ref.isdigit()
            or type(self.order_sys_id) is not str
            or not self.order_sys_id
            or type(self.exchange_id) is not str
            or not self.exchange_id
            or type(self.front_id) is not int
            or self.front_id <= 0
            or type(self.session_id) is not int
            or self.session_id <= 0
            or type(self.quantity) is not int
            or self.quantity <= 0
            or type(self.traded_quantity) is not int
            or not 0 <= self.traded_quantity < self.quantity
            or type(self.remaining_quantity) is not int
            or self.remaining_quantity != self.quantity - self.traded_quantity
            or type(self.issued_monotonic_ns) is not int
            or type(self.expires_monotonic_ns) is not int
            or self.expires_monotonic_ns <= self.issued_monotonic_ns
            or not isinstance(self.expires_at_utc, datetime)
            or self.expires_at_utc.tzinfo is None
            or self._issuer is None
        ):
            _reject("native_order_target_observation_invalid")

    @property
    def authorizes_cancel(self) -> bool:
        """This SDK query observation never grants cancel authority."""

        return False

    @property
    def is_fresh(self) -> bool:
        """Compare against this process's monotonic clock, never a caller clock."""

        return time.monotonic_ns() < self.expires_monotonic_ns


def _sdk_contracts() -> tuple[Any, ...]:
    """Load the exact installed SDK contracts lazily; absence rejects closed."""

    try:
        from bt_api_ctp.ctp.client import TraderClient
        from bt_api_ctp.order_action import CtpOrderActionEvidence
        from bt_api_ctp.query import (
            QueryResult,
            _QUERY_SCOPE_SEAL,
            _QUERY_SOURCE_SEAL,
            _QuerySessionScope,
            _QuerySource,
            _query_records_digest,
        )
        from bt_api_ctp.containers.ctp.ctp_native_query_certificate import (
            _same_scope,
            _scope_for_client,
            _source_for_result,
        )
    except Exception as exc:
        raise CtpSimulationExecutionError("native_query_sdk_contract_unavailable") from exc
    return (
        TraderClient,
        CtpOrderActionEvidence,
        QueryResult,
        _QUERY_SCOPE_SEAL,
        _QUERY_SOURCE_SEAL,
        _QuerySessionScope,
        _QuerySource,
        _query_records_digest,
        _same_scope,
        _scope_for_client,
        _source_for_result,
    )


class CtpTraderClientQueryEvidenceVerifier:
    """Verify TraderClient-issued query evidence and callback readback.

    The verifier only accepts the exact installed SDK ``TraderClient`` type.
    It checks the SDK's sealed query source, scope, terminal marker, records
    digest, request filters, current-result readback, and late-callback count.
    Each later ``verify`` call rechecks all query results previously accepted
    by this verifier. If the SDK evicts a result from its bounded query
    history, verification stops succeeding for this session.
    """

    def __init__(
        self,
        trader_client: Any,
        registration: CtpSimulationExecutionRegistration,
    ) -> None:
        if type(registration) is not CtpSimulationExecutionRegistration:
            _reject("code_owned_registration_required")
        contracts = _sdk_contracts()
        TraderClient = contracts[0]
        if type(trader_client) is not TraderClient:
            _reject("native_query_trader_client_type_invalid")
        self._trader = trader_client
        self.registration = registration
        self._created_monotonic = time.monotonic()
        self._accepted_queries: dict[int, tuple[Any, str, str, tuple[tuple[str, str], ...]]] = {}
        self._accepted_actions: dict[tuple[int, str], Any] = {}
        self._query_state_lock = getattr(trader_client, "_query_state_lock", None)
        if self._query_state_lock is None or not callable(
            getattr(self._query_state_lock, "__enter__", None)
        ):
            _reject("native_query_quiescence_lock_unavailable")
        action_late_count = getattr(trader_client, "_order_action_late_callback_count", None)
        if type(action_late_count) is not int or action_late_count < 0:
            _reject("native_query_action_quiescence_unavailable")
        self._initial_action_late_callback_count = action_late_count
        self.last_error_code: str | None = None
        self._contracts = contracts
        try:
            self._initial_scope = contracts[9](trader_client)
            self._check_registered_scope(self._initial_scope)
        except Exception as exc:
            raise CtpSimulationExecutionError("native_query_initial_scope_invalid") from exc

    def verify(
        self,
        query_kind: str,
        result: CtpSimulationQueryResult,
        *,
        expected_identity: CtpSimulationSessionIdentity,
        registration_digest: str,
    ) -> bool:
        """Return true only for current, same-session SDK native evidence."""

        try:
            self._verify(query_kind, result, expected_identity, registration_digest)
            self.last_error_code = None
            return True
        except Exception as exc:
            code = getattr(exc, "reason", getattr(exc, "code", None))
            self.last_error_code = code if type(code) is str else "native_query_evidence_invalid"
            return False

    def _verify(
        self,
        query_kind: str,
        result: CtpSimulationQueryResult,
        expected_identity: CtpSimulationSessionIdentity,
        registration_digest: str,
    ) -> None:
        if type(expected_identity) is not CtpSimulationSessionIdentity:
            _reject("native_query_expected_identity_invalid")
        if type(registration_digest) is not str or registration_digest != self.registration.digest:
            _reject("native_query_registration_mismatch")
        if type(result) is not CtpSimulationQueryResult or result.complete is not True:
            _reject("native_query_result_incomplete")
        if type(result.records) is not tuple or result.identity != expected_identity:
            _reject("native_query_result_identity_mismatch")
        self._check_runtime_identity(expected_identity)

        if query_kind == "cancel_requests":
            self._verify_cancel_result(result, expected_identity)
        else:
            expected_type = {
                "orders": "orders",
                "trades": "trades",
                "positions": "positions",
                "account_open_orders": "orders",
            }.get(query_kind)
            if expected_type is None:
                _reject("native_query_kind_unsupported")
            native = result.native_evidence
            scope, source = self._verify_query_result(
                native,
                expected_type=expected_type,
                expected_identity=expected_identity,
                filters=self._expected_filters(query_kind, scope=None),
            )
            self._verify_projected_records(
                query_kind, result.records, native, expected_identity, scope
            )
            self._capture_query(native, source)
            self._check_registered_scope(scope)

        self._recheck_quiescence()

    def _current_scope(self) -> Any:
        return self._contracts[9](self._trader)

    def verify_order_target(
        self,
        scope: Any,
        reservation: Any,
        native_query_evidence: Any,
    ) -> CtpSimulationOrderTargetObservation:
        """Derive a short-lived target observation from the exact SDK query row.

        This is an observation only. It does not issue an I9 verifier receipt,
        persist a cancel target, or authorize dispatch. Freshness uses the
        SDK-issued monotonic expiry and this process's monotonic clock; callers
        cannot supply a row, verifier, or clock.
        """

        if type(native_query_evidence) is not CtpSimulationQueryResult:
            _reject("native_order_target_query_result_invalid")

        identity_fields = ("account_key", "trading_day", "scope_key")
        scope_identity: dict[str, str] = {}
        reservation_identity: dict[str, str] = {}
        try:
            for name in identity_fields:
                scope_value = getattr(scope, name)
                reservation_value = getattr(reservation, name)
                if (
                    type(scope_value) is not str
                    or not scope_value
                    or type(reservation_value) is not str
                    or not reservation_value
                ):
                    _reject("native_order_target_reservation_identity_invalid")
                scope_identity[name] = scope_value
                reservation_identity[name] = reservation_value
            intent_id = getattr(reservation, "managed_intent_id")
            runtime_order_id = getattr(reservation, "runtime_order_id")
            order_ref = getattr(reservation, "order_ref")
        except CtpSimulationExecutionError:
            raise
        except Exception:
            _reject("native_order_target_reservation_identity_invalid")
        if scope_identity != reservation_identity:
            _reject("native_order_target_reservation_scope_mismatch")
        if (
            type(intent_id) is not str
            or not intent_id
            or type(runtime_order_id) is not str
            or not runtime_order_id
            or type(order_ref) is not str
            or len(order_ref) != 12
            or not order_ref.isascii()
            or not order_ref.isdigit()
        ):
            _reject("native_order_target_reservation_identity_invalid")

        result = native_query_evidence
        if type(result.identity) is not CtpSimulationSessionIdentity:
            _reject("native_order_target_query_identity_invalid")
        if result.identity.trading_day != reservation_identity["trading_day"]:
            _reject("native_order_target_trading_day_mismatch")
        if not self.verify(
            "account_open_orders",
            result,
            expected_identity=result.identity,
            registration_digest=self.registration.digest,
        ):
            _reject(self.last_error_code or "native_order_target_query_unverified")

        native = result.native_evidence
        QueryResult = self._contracts[2]
        source_for_result = self._contracts[10]
        if type(native) is not QueryResult:
            _reject("native_order_target_sdk_result_unavailable")

        # The SDK result and source are read again under the SDK's callback
        # lock. This closes the interval after the public verification call;
        # no caller-supplied projected row or timestamp is used as evidence.
        with self._query_state_lock:
            current_scope = self._current_scope()
            if (
                not self._contracts[8](self._initial_scope, current_scope)
                or current_scope.trading_day != result.identity.trading_day
                or current_scope.connection_generation != result.identity.connection_generation
            ):
                _reject("native_order_target_session_generation_changed")
            self._check_registered_scope(current_scope)
            verified_scope, source = self._verify_query_result(
                native,
                expected_type="orders",
                expected_identity=result.identity,
                filters=self._expected_filters("account_open_orders", current_scope),
            )
            current = self._current_query(native.request_id)
            current_source = source_for_result(
                current,
                current_scope,
                now_utc=datetime.now(timezone.utc),
                now_monotonic=time.monotonic(),
            )
            if (
                current_source.issuer is not source.issuer
                or current_source.request_type != source.request_type
                or current_source.request_id != source.request_id
                or current_source.account_fingerprint != source.account_fingerprint
                or current_source.connection_generation != source.connection_generation
                or current_source.trading_day != source.trading_day
                or current_source.request_filters != source.request_filters
                or current_source.explicit_request_filters != source.explicit_request_filters
                or current_source.records_sha256 != source.records_sha256
                or current_source.started_monotonic != source.started_monotonic
                or current_source.completed_monotonic != source.completed_monotonic
            ):
                _reject("native_order_target_current_source_changed")
            self._verify_projected_records(
                "account_open_orders",
                result.records,
                current,
                result.identity,
                verified_scope,
            )
            self._capture_query(current, current_source)
            self._recheck_quiescence()

            matches = tuple(
                row
                for row in current.records
                if _text(_value(row, "OrderRef", "order_ref")) == order_ref
            )
            if len(matches) != 1:
                _reject("native_order_target_native_row_ambiguous")
            target_row = matches[0]
            target = self._order_snapshot(target_row, client_order_id=None)
            remaining = target.quantity - target.traded_quantity
            if (
                target.order_ref != order_ref
                or target.instrument_id != self.registration.instrument_id
                or target.exchange_id != self.registration.exchange_id
                or target.status not in {"OPEN", "PARTIAL"}
                or remaining <= 0
                or target.status == "OPEN" and target.traded_quantity != 0
                or target.status == "PARTIAL"
                and not 0 < target.traded_quantity < target.quantity
                or not target.order_sys_id
                or target.front_id <= 0
                or target.session_id <= 0
            ):
                _reject("native_order_target_native_row_mismatch")

            request_digest, source_digest = self._order_target_source_digests(
                current_source
            )
            reservation_digest = _canonical_digest(
                b"backtrader.ctp.order-target-reservation.v1\0",
                {
                    "account_key": reservation_identity["account_key"],
                    "trading_day": reservation_identity["trading_day"],
                    "scope_key": reservation_identity["scope_key"],
                    "managed_intent_id": intent_id,
                    "runtime_order_id": runtime_order_id,
                    "order_ref": order_ref,
                },
            )
            issued_ns = time.monotonic_ns()
            source_expiry_ns = int(current_source.trusted_expires_monotonic * 1_000_000_000)
            expiry_ns = min(
                source_expiry_ns,
                issued_ns + _ORDER_TARGET_OBSERVATION_TTL_NS,
            )
            if expiry_ns <= issued_ns:
                _reject("native_order_target_query_expired")
            expires_at_utc = min(
                current_source.trusted_expires_at_utc,
                datetime.now(timezone.utc)
                + timedelta(microseconds=(expiry_ns - issued_ns) // 1000),
            )
            return CtpSimulationOrderTargetObservation(
                registration_digest=self.registration.digest,
                reservation_digest=reservation_digest,
                request_digest=request_digest,
                source_digest=source_digest,
                request_id=current.request_id,
                request_type=current.request_type,
                account_fingerprint=current_source.account_fingerprint,
                trading_day=current_source.trading_day,
                connection_generation=current_source.connection_generation,
                order_ref=target.order_ref,
                order_sys_id=target.order_sys_id,
                exchange_id=target.exchange_id,
                front_id=target.front_id,
                session_id=target.session_id,
                quantity=target.quantity,
                traded_quantity=target.traded_quantity,
                remaining_quantity=remaining,
                issued_monotonic_ns=issued_ns,
                expires_monotonic_ns=expiry_ns,
                expires_at_utc=expires_at_utc,
                _seal=_ORDER_TARGET_OBSERVATION_SEAL,
                _issuer=current_source.issuer,
            )

    @staticmethod
    def _order_target_source_digests(source: Any) -> tuple[str, str]:
        request_payload = {
            "request_type": source.request_type,
            "request_id": source.request_id,
            "request_filters": [list(item) for item in source.request_filters],
            "explicit_request_filters": list(source.explicit_request_filters),
        }
        request_digest = _canonical_digest(
            b"backtrader.ctp.order-target-request.v1\0", request_payload
        )
        source_digest = _canonical_digest(
            b"backtrader.ctp.order-target-source.v1\0",
            {
                "request_digest": request_digest,
                "issuer_instance": id(source.issuer),
                "account_fingerprint": source.account_fingerprint,
                "trading_day": source.trading_day,
                "connection_generation": source.connection_generation,
                "broker_id": source.broker_id,
                "investor_id": source.investor_id,
                "started_at_utc": source.started_at_utc.isoformat(),
                "completed_at_utc": source.completed_at_utc.isoformat(),
                "started_monotonic": float(source.started_monotonic).hex(),
                "completed_monotonic": float(source.completed_monotonic).hex(),
                "clock_domain_id": source.clock_domain_id,
                "records_sha256": source.records_sha256,
                "trusted_expires_at_utc": source.trusted_expires_at_utc.isoformat(),
                "trusted_expires_monotonic": float(
                    source.trusted_expires_monotonic
                ).hex(),
            },
        )
        return request_digest, source_digest

    def _check_registered_scope(self, scope: Any) -> None:
        registration = self.registration
        if (
            scope.read_only_ready is not True
            or scope.connection_generation <= 0
            or scope.trading_day != _text(getattr(self._trader, "_trading_day", ""))
            or _text(getattr(self._trader, "_bound_front", "")) != registration.td_front
            or _text(getattr(self._trader, "_bound_md_front", "")) != registration.md_front
            or _text(getattr(self._trader, "_bound_broker_id", "")) == ""
            or _text(getattr(self._trader, "_bound_user_id", "")) == ""
            or getattr(self._trader, "ctp_env_profile", None) != registration.sdk_profile
            or hashlib.sha256(("acct_" + scope.account_fingerprint).encode("ascii")).hexdigest()
            != registration.account_fingerprint_sha256
        ):
            _reject("native_query_registered_scope_mismatch")
        front_state_getter = getattr(self._trader, "get_front_binding_state", None)
        if callable(front_state_getter):
            try:
                front_state = front_state_getter()
            except Exception:
                _reject("native_query_front_binding_unavailable")
            if (
                not isinstance(front_state, dict)
                or front_state.get("configured_front") != registration.td_front
                or front_state.get("registered_front") != registration.td_front
                or front_state.get("connection_confirmed_front") != registration.td_front
                or front_state.get("connected") is not True
                or front_state.get("native_api_current") is not True
                or front_state.get("bound_identity_current") is not True
                or front_state.get("connection_generation") != scope.connection_generation
            ):
                _reject("native_query_front_binding_mismatch")
        else:
            bound_check = getattr(self._trader, "_bound_identity_is_current", None)
            native_api = getattr(self._trader, "_api", None)
            if (
                not callable(bound_check)
                or bound_check(require_active_front=True) is not True
                or _text(getattr(self._trader, "_session_native_front", ""))
                != registration.td_front
                or native_api is None
                or native_api is not getattr(self._trader, "_session_native_api", None)
                or getattr(self._trader, "_connected", None) is not True
            ):
                _reject("native_query_front_binding_mismatch")

    def _check_runtime_identity(self, identity: CtpSimulationSessionIdentity) -> None:
        registration = self.registration
        if (
            identity.environment != registration.environment
            or identity.sdk_profile != registration.sdk_profile
            or identity.td_front != registration.td_front
            or identity.md_front != registration.md_front
            or identity.account_fingerprint_sha256 != registration.account_fingerprint_sha256
            or identity.production is not False
            or identity.native_simnow_managed_mode is not True
            or identity.native_gate_armed is not False
        ):
            _reject("native_query_runtime_identity_mismatch")
        scope = self._current_scope()
        if (
            not self._contracts[8](self._initial_scope, scope)
            or scope.trading_day != identity.trading_day
            or scope.connection_generation != identity.connection_generation
        ):
            _reject("native_query_session_generation_changed")
        self._check_registered_scope(scope)

    def _expected_filters(self, query_kind: str, scope: Any) -> dict[str, str]:
        if scope is None:
            scope = self._current_scope()
        account = {"BrokerID": scope.broker_id, "InvestorID": scope.investor_id}
        if query_kind == "positions":
            return account
        if query_kind in ("orders", "trades"):
            if query_kind == "orders":
                return {
                    **account,
                    "InstrumentID": self.registration.instrument_id,
                    "ExchangeID": self.registration.exchange_id,
                    "OrderSysID": "",
                }
            return {
                **account,
                "InstrumentID": self.registration.instrument_id,
                "ExchangeID": self.registration.exchange_id,
                "TradeID": "",
                "TradeTimeStart": "",
                "TradeTimeEnd": "",
            }
        if query_kind == "account_open_orders":
            return {
                **account,
                "InstrumentID": "",
                "ExchangeID": "",
                "OrderSysID": "",
            }
        _reject("native_query_filter_kind_unsupported")

    def _verify_query_result(
        self,
        native: Any,
        *,
        expected_type: str,
        expected_identity: CtpSimulationSessionIdentity,
        filters: dict[str, str],
    ) -> tuple[Any, Any]:
        (
            _TraderClient,
            _ActionEvidence,
            QueryResult,
            _scope_seal,
            _source_seal,
            _QuerySessionScope,
            _QuerySource,
            _records_digest,
            _same_scope,
            _scope_for_client,
            source_for_result,
        ) = self._contracts
        if type(native) is not QueryResult:
            _reject("native_query_sdk_result_type_invalid")
        scope = _scope_for_client(self._trader)
        self._check_registered_scope(scope)
        if (
            native.request_type != expected_type
            or native.connection_generation != expected_identity.connection_generation
            or native.account_fingerprint != scope.account_fingerprint
            or native.complete is not True
            or native.is_last_seen is not True
            or native.timed_out is not False
            or native.unsupported is not False
            or native.error_code not in (None, 0)
            or native.error_message != ""
            or native.submit_code not in (None, 0)
            or native.late_callback_count != 0
        ):
            _reject("native_query_sdk_result_incomplete")
        source = source_for_result(
            native,
            scope,
            now_utc=datetime.now(timezone.utc),
            now_monotonic=time.monotonic(),
        )
        if (
            source.started_monotonic < self._created_monotonic
            or dict(source.request_filters) != filters
            or source.explicit_request_filters != ()
        ):
            _reject("native_query_sdk_source_scope_mismatch")
        current = self._current_query(native.request_id)
        current_source = current.query_source
        if current.late_callback_count != 0:
            _reject("native_query_late_callback_detected")
        if (
            current.request_type != native.request_type
            or current.request_id != native.request_id
            or current.account_fingerprint != native.account_fingerprint
            or current.connection_generation != native.connection_generation
            or current.complete is not True
            or current.is_last_seen is not True
            or current.timed_out is not False
            or current.unsupported is not False
            or current.error_code not in (None, 0)
            or current.error_message != ""
            or current.submit_code not in (None, 0)
            or type(current_source) is not _QuerySource
            or current_source._seal is not _source_seal
            or current_source.issuer is not source.issuer
            or current_source.request_type != source.request_type
            or current_source.request_id != source.request_id
            or current_source.records_sha256 != source.records_sha256
            or current_source.request_filters != source.request_filters
            or current_source.explicit_request_filters != source.explicit_request_filters
            or _records_digest(current.records) != source.records_sha256
        ):
            _reject("native_query_current_result_mismatch")
        return scope, source

    def _capture_query(self, native: Any, source: Any) -> None:
        entry = (
            native,
            source.request_type,
            source.records_sha256,
            source.request_filters,
        )
        previous = self._accepted_queries.get(native.request_id)
        if previous is not None and previous[1:] != entry[1:]:
            _reject("native_query_request_id_reused")
        self._accepted_queries[native.request_id] = entry

    def _current_query(self, request_id: int) -> Any:
        getter = getattr(self._trader, "get_query_result", None)
        if not callable(getter):
            _reject("native_query_current_result_unavailable")
        try:
            result = getter(request_id)
        except Exception:
            _reject("native_query_current_result_unavailable")
        if result is None:
            _reject("native_query_history_evicted")
        QueryResult = self._contracts[2]
        if type(result) is not QueryResult:
            _reject("native_query_current_result_type_invalid")
        return result

    def _recheck_quiescence(self) -> None:
        _query_records_digest = self._contracts[7]
        source_for_result = self._contracts[10]
        with self._query_state_lock:
            current_scope = self._current_scope()
            if not self._contracts[8](self._initial_scope, current_scope):
                _reject("native_query_session_generation_changed")
            self._check_registered_scope(current_scope)
            for request_id, (_original, request_type, records_digest, filters) in tuple(
                self._accepted_queries.items()
            ):
                current = self._current_query(request_id)
                source = current.query_source
                if (
                    current.request_type != request_type
                    or current.request_id != request_id
                    or current.complete is not True
                    or current.is_last_seen is not True
                    or current.timed_out is not False
                    or current.unsupported is not False
                    or current.error_code not in (None, 0)
                    or current.error_message != ""
                    or current.submit_code not in (None, 0)
                    or current.late_callback_count != 0
                    or type(source) is not self._contracts[6]
                    or source._seal is not self._contracts[4]
                    or source.issuer is not self._initial_scope.issuer
                    or source.request_type != request_type
                    or source.request_id != request_id
                    or source.connection_generation != self._initial_scope.connection_generation
                    or source.trading_day != self._initial_scope.trading_day
                    or source.records_sha256 != records_digest
                    or source.request_filters != filters
                    or _query_records_digest(current.records) != records_digest
                ):
                    _reject("native_query_late_callback_or_mutation")
                try:
                    source_for_result(
                        current,
                        current_scope,
                        now_utc=datetime.now(timezone.utc),
                        now_monotonic=time.monotonic(),
                        expiry_error_code="query_expired_during_quiescence",
                    )
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    _reject(code if type(code) is str else "native_query_quiescence_source_invalid")

            current_late_count = getattr(self._trader, "_order_action_late_callback_count", None)
            if current_late_count != self._initial_action_late_callback_count:
                _reject("native_cancel_late_callback_detected")
            getter = getattr(self._trader, "get_order_action_evidence", None)
            if self._accepted_actions and not callable(getter):
                _reject("native_cancel_query_history_unavailable")
            for (request_id, action_ref), original in tuple(self._accepted_actions.items()):
                try:
                    current = getter(request_id, order_action_ref=action_ref)
                except Exception:
                    _reject("native_cancel_query_history_unavailable")
                if current is not original:
                    _reject("native_cancel_query_history_changed")

    def _verify_projected_records(
        self,
        query_kind: str,
        records: tuple[Any, ...],
        native: Any,
        identity: CtpSimulationSessionIdentity,
        scope: Any,
    ) -> None:
        for native_row in native.records:
            self._validate_row_scope(native_row, scope)
        if query_kind in ("orders", "account_open_orders"):
            if any(type(record) is not CtpSimulationOrderSnapshot for record in records):
                _reject("native_query_order_projection_invalid")
            if query_kind == "account_open_orders":
                expected = tuple(
                    self._order_snapshot(row, client_order_id=None)
                    for row in native.records
                    if self._is_open(row)
                )
            else:
                if len(records) > 1:
                    _reject("native_query_order_projection_ambiguous")
                client_order_id = records[0].client_order_id if records else ""
                if not client_order_id:
                    _reject("native_query_order_projection_missing_identity")
                order_ref = records[0].order_ref
                rows = tuple(
                    row
                    for row in native.records
                    if _text(_value(row, "OrderRef", "order_ref")) == order_ref
                )
                if len(rows) != len(records) or len(rows) != 1:
                    _reject("native_query_order_projection_mismatch")
                expected = (self._order_snapshot(rows[0], client_order_id),)
            if records != expected:
                _reject("native_query_order_projection_mismatch")
            if query_kind == "orders" and records:
                self._order_ref_by_client[records[0].client_order_id] = records[0].order_ref
            return

        if query_kind == "trades":
            if any(type(record) is not CtpSimulationTradeSnapshot for record in records):
                _reject("native_query_trade_projection_invalid")
            if not records:
                known_order_refs = tuple(self._order_ref_by_client.values())
                if not known_order_refs or any(
                    _text(_value(row, "OrderRef", "order_ref")) in known_order_refs
                    for row in native.records
                ):
                    _reject("native_query_trade_order_identity_missing")
                return
            client_order_ids = {record.client_order_id for record in records}
            if len(client_order_ids) != 1:
                _reject("native_query_trade_projection_ambiguous")
            client_order_id = next(iter(client_order_ids))
            order_ref = self._order_ref_by_client.get(client_order_id)
            if not order_ref:
                _reject("native_query_trade_order_identity_missing")
            expected = tuple(
                CtpSimulationTradeSnapshot(
                    client_order_id=client_order_id,
                    trade_id=_text(_value(row, "TradeID", "trade_id")),
                    quantity=_int(row, "Volume", "quantity"),
                    instrument_id=_text(_value(row, "InstrumentID", "instrument_id")),
                    exchange_id=_text(_value(row, "ExchangeID", "exchange_id")),
                    side={"0": "BUY", "1": "SELL"}.get(
                        _text(_value(row, "Direction", "direction")), ""
                    ),
                )
                for row in native.records
                if _text(_value(row, "OrderRef", "order_ref")) == order_ref
            )
            if records != expected:
                _reject("native_query_trade_projection_mismatch")
            return

        if query_kind == "positions":
            if any(type(record) is not CtpSimulationPositionSnapshot for record in records):
                _reject("native_query_position_projection_invalid")
            totals = {"BUY": 0, "SELL": 0}
            for row in native.records:
                if (
                    _text(_value(row, "InstrumentID", "instrument_id"))
                    != self.registration.instrument_id
                    or _text(_value(row, "ExchangeID", "exchange_id"))
                    != self.registration.exchange_id
                ):
                    continue
                if _text(_value(row, "HedgeFlag", "hedge_flag")) != self.registration.hedge_flag:
                    _reject("native_query_position_hedge_scope_mismatch")
                side = {"2": "BUY", "3": "SELL"}.get(
                    _text(_value(row, "PosiDirection", "position_direction"))
                )
                if side is None:
                    _reject("native_query_position_direction_unproven")
                totals[side] += _int(row, "Position", "quantity")
            expected = tuple(
                CtpSimulationPositionSnapshot(
                    self.registration.instrument_id,
                    self.registration.exchange_id,
                    side,
                    quantity,
                )
                for side, quantity in totals.items()
            )
            if records != expected:
                _reject("native_query_position_projection_mismatch")
            return

    @property
    def _order_ref_by_client(self) -> dict[str, str]:
        if not hasattr(self, "__order_ref_by_client"):
            self.__order_ref_by_client: dict[str, str] = {}
        return self.__order_ref_by_client

    @staticmethod
    def _is_open(row: Any) -> bool:
        status = _text(_value(row, "OrderStatus", "order_status")).lower()
        if status in {"0", "2", "4", "5"}:
            return False
        if status not in {"1", "3", "a", "b", "c"}:
            _reject("native_query_order_status_unproven")
        return True

    @staticmethod
    def _order_snapshot(
        row: Any,
        client_order_id: str | None,
    ) -> CtpSimulationOrderSnapshot:
        order_ref = _text(_value(row, "OrderRef", "order_ref"))
        submit_status = _text(_value(row, "OrderSubmitStatus", "order_submit_status"))
        raw_status = _text(_value(row, "OrderStatus", "order_status")).lower()
        traded = _int(row, "VolumeTraded", "traded_quantity", optional=True)
        quantity = _int(row, "VolumeTotalOriginal", "quantity")
        if submit_status == "4":
            status = "REJECTED"
        elif raw_status == "0":
            status = "FILLED"
        elif raw_status in {"1", "3"}:
            status = "PARTIAL" if traded else "OPEN"
        elif raw_status in {"2", "4", "5"}:
            status = "CANCELED"
        else:
            _reject("native_query_order_status_unproven")
        return CtpSimulationOrderSnapshot(
            client_order_id=client_order_id or order_ref,
            instrument_id=_text(_value(row, "InstrumentID", "instrument_id")),
            exchange_id=_text(_value(row, "ExchangeID", "exchange_id")),
            side={"0": "BUY", "1": "SELL"}.get(_text(_value(row, "Direction", "side")), ""),
            quantity=quantity,
            limit_price=_decimal(row, "LimitPrice", "limit_price"),
            traded_quantity=traded,
            status=status,
            order_ref=order_ref,
            order_sys_id=_text(_value(row, "OrderSysID", "order_sys_id")),
            front_id=_int(row, "FrontID", "front_id"),
            session_id=_int(row, "SessionID", "session_id"),
        )

    def _verify_cancel_result(
        self,
        result: CtpSimulationQueryResult,
        expected_identity: CtpSimulationSessionIdentity,
    ) -> None:
        if any(
            type(record) is not CtpSimulationCancelRequestSnapshot
            or record.status not in {"CANCELED", "REJECTED"}
            for record in result.records
        ):
            _reject("native_cancel_query_not_terminal")
        action_ids = tuple(record.action_id for record in result.records)
        if not action_ids or len(set(action_ids)) != len(action_ids):
            _reject("native_cancel_query_coverage_invalid")
        evidence_bundle = result.native_evidence
        if type(evidence_bundle) is not tuple:
            _reject("native_cancel_query_evidence_missing")
        target_keys = tuple(
            (
                record.target_order_ref,
                record.target_order_sys_id,
                record.target_front_id,
                record.target_session_id,
            )
            for record in result.records
        )
        if len(set(target_keys)) != len(target_keys):
            _reject("native_cancel_query_target_ambiguous")
        ActionEvidence = self._contracts[1]
        cursor = 0
        seen_request_ids: set[int] = set()
        for record in result.records:
            if cursor >= len(evidence_bundle):
                _reject("native_cancel_query_coverage_invalid")
            evidence = evidence_bundle[cursor]
            cursor += 1
            if type(evidence) is not ActionEvidence:
                _reject("native_cancel_query_action_evidence_invalid")
            request_id = evidence.request_id
            if type(request_id) is not int or request_id <= 0 or request_id in seen_request_ids:
                _reject("native_cancel_query_action_identity_invalid")
            seen_request_ids.add(request_id)
            getter = getattr(self._trader, "get_order_action_evidence", None)
            if not callable(getter):
                _reject("native_cancel_query_history_unavailable")
            try:
                stored = getter(request_id, order_action_ref=request_id)
            except Exception:
                _reject("native_cancel_query_history_unavailable")
            if stored is not evidence:
                _reject("native_cancel_query_history_mismatch")
            if (
                evidence.order_action_ref != str(request_id)
                or evidence.callback_received is not True
                or evidence.evidence_received is not True
                or evidence.evidence_source != "OnRspOrderAction"
                or evidence.connection_generation != expected_identity.connection_generation
                or evidence.trading_day != expected_identity.trading_day
                or evidence.account_fingerprint != "acct_" + self._initial_scope.account_fingerprint
                or evidence.order_ref != record.target_order_ref
                or evidence.order_sys_id != record.target_order_sys_id
                or evidence.front_id != record.target_front_id
                or evidence.session_id != record.target_session_id
                or evidence.action_flag != "0"
                or evidence.instrument_id != self.registration.instrument_id
                or evidence.exchange_id != self.registration.exchange_id
                or evidence.status not in {"accepted", "rejected"}
                or evidence.reason not in {"cancel_request_accepted", "native_cancel_rejected"}
            ):
                _reject("native_cancel_query_action_scope_mismatch")
            self._accepted_actions[(request_id, str(request_id))] = evidence

            if evidence.status == "rejected":
                if record.status != "REJECTED":
                    _reject("native_cancel_query_action_status_mismatch")
                continue

            if record.status != "CANCELED" or cursor >= len(evidence_bundle):
                _reject("native_cancel_query_target_not_terminal")
            target_result = evidence_bundle[cursor]
            cursor += 1
            filters = self._expected_target_order_filters(
                self._initial_scope, record.target_order_sys_id
            )
            target_scope, source = self._verify_query_result(
                target_result,
                expected_type="orders",
                expected_identity=expected_identity,
                filters=filters,
            )
            if (
                len(target_result.records) != 1
                or _text(_value(target_result.records[0], "OrderRef", "order_ref"))
                != record.target_order_ref
                or _text(_value(target_result.records[0], "OrderSysID", "order_sys_id"))
                != record.target_order_sys_id
                or _text(_value(target_result.records[0], "InstrumentID", "instrument_id"))
                != self.registration.instrument_id
                or _text(_value(target_result.records[0], "ExchangeID", "exchange_id"))
                != self.registration.exchange_id
            ):
                _reject("native_cancel_query_target_readback_mismatch")
            self._validate_row_scope(target_result.records[0], target_scope)
            target_snapshot = self._order_snapshot(target_result.records[0], None)
            if (
                target_snapshot.status != "CANCELED"
                or target_snapshot.order_ref != record.target_order_ref
                or target_snapshot.order_sys_id != record.target_order_sys_id
                or target_snapshot.front_id != record.target_front_id
                or target_snapshot.session_id != record.target_session_id
            ):
                _reject("native_cancel_query_target_readback_mismatch")
            self._capture_query(target_result, source)

        if cursor != len(evidence_bundle):
            _reject("native_cancel_query_evidence_extra")

    def _expected_target_order_filters(self, scope: Any, order_sys_id: str) -> dict[str, str]:
        return {
            "BrokerID": scope.broker_id,
            "InvestorID": scope.investor_id,
            "InstrumentID": self.registration.instrument_id,
            "ExchangeID": self.registration.exchange_id,
            "OrderSysID": order_sys_id,
        }

    @staticmethod
    def _validate_row_scope(row: Any, scope: Any) -> None:
        for names, expected in (
            (("BrokerID", "broker_id"), scope.broker_id),
            (("InvestorID", "investor_id"), scope.investor_id),
            (("TradingDay", "trading_day"), scope.trading_day),
        ):
            value = _value(row, *names)
            if value is not None and _text(value) != expected:
                _reject("native_query_row_scope_mismatch")


__all__ = [
    "CtpSimulationOrderTargetObservation",
    "CtpTraderClientQueryEvidenceVerifier",
]
