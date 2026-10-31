"""SDK-backed CTP read-only session for a sealed CTP sandbox account scope.

This module has no import-time SDK dependency or operator-selected endpoint.
The caller must first validate a sealed ``simulation/sandbox`` runtime and
construct this factory from its code-owned account and instrument scope.
Opening a session performs authentication and native queries only; this module
has no order, cancellation, settlement, or execution-arm operation.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, Tuple
from urllib.parse import urlsplit

from .ctp_preflight import (
    CtpReadOnlyQuerySnapshot,
    CtpReadOnlySessionIdentity,
    CtpReadOnlySessionRequest,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_HEDGE_RE = re.compile(r"^[1-3]$")
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WRITE_REQUEST_KEYS = ("settlement_confirm", "order_insert", "order_action")
_QUERY_ORDER = (
    ("account", "query_account_result"),
    ("positions", "query_positions_result"),
    ("orders", "query_orders_result"),
    ("trades", "query_trades_result"),
    ("instruments", "query_instruments_result"),
    ("margin_rate", "query_instrument_margin_rate_result"),
    ("commission_rate", "query_instrument_commission_rate_result"),
)
_SNAPSHOT_NAMES = {
    "margin_rate": "margin_rates",
    "commission_rate": "commission_rates",
}
_RATE_QUERY_NAMES = frozenset(("margin_rate", "commission_rate"))
_NATIVE_CERTIFICATE_SCHEMA = "ctp_native_query_certificate.v5"
_RATE_EXCHANGE_SCOPE_VALUES = frozenset(("exact", "unverified"))
_MAX_CLOSE_JOIN_WAIT_SECONDS = 1.0
_MISSING_STOP_AND_WAIT = object()
_CTP_REQUEST_COUNTER_KEYS = (
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


class CtpSdkReadOnlyError(ValueError):
    """Redacted failure of one native read-only session."""

    def __init__(self, reason: str, cleanup_reason: Optional[str] = None) -> None:
        self.reason = reason
        self.cleanup_reason = cleanup_reason
        message = "CTP read-only SDK session rejected: {0}".format(reason)
        if cleanup_reason is not None:
            message += " (cleanup: {0})".format(cleanup_reason)
        super().__init__(message)


@dataclass(frozen=True)
class CtpSdkReadOnlyCloseEvidence:
    """Value-free projection of one read-only native-client close attempt.

    ``status`` is ``complete`` only when a trusted SDK stop receipt positively
    proves native release and completed Join.  ``native_join_pending`` is used
    only when a structurally valid receipt explicitly reports a required,
    incomplete Join.  Missing, inconsistent, or exceptional evidence remains
    ``unknown``.  This projection describes shutdown only; it is not account,
    settlement, query-snapshot, or trading-readiness evidence.
    """

    status: str
    native_released: Optional[bool] = None
    join_required: Optional[bool] = None
    join_completed: Optional[bool] = None
    thread_alive: Optional[bool] = None
    timed_out: Optional[bool] = None
    client_stop_returned: Optional[bool] = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in (
            "complete",
            "native_join_pending",
            "unknown",
        ):
            raise ValueError("close_evidence_invalid")
        for name in (
            "native_released",
            "join_required",
            "join_completed",
            "thread_alive",
            "timed_out",
            "client_stop_returned",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError("close_evidence_invalid")
        if self.status == "complete" and not (
            self.native_released is True
            and self.join_required in (True, False)
            and (self.join_required is False or self.join_completed is True)
            and self.thread_alive is False
            and self.timed_out is False
            and self.client_stop_returned is True
        ):
            raise ValueError("close_evidence_invalid")
        if self.status == "native_join_pending" and not (
            self.join_required is True and self.join_completed is False
        ):
            raise ValueError("close_evidence_invalid")

    @property
    def native_join_pending(self) -> bool:
        return self.status == "native_join_pending"

    @property
    def verified_complete(self) -> bool:
        return self.status == "complete"


def _reject(reason: str) -> None:
    raise CtpSdkReadOnlyError(reason) from None


def _close_ctp_sdk_client_read_only(
    client: Any,
    *,
    stop_receipt_type: Optional[Any] = None,
    expected_connection_generation: Optional[int] = None,
) -> None:
    """Stop one native client and require positive bounded shutdown evidence."""

    try:
        stop_and_wait = getattr(client, "stop_and_wait", _MISSING_STOP_AND_WAIT)
    except Exception:
        _reject("session_close_method_unknown")
    if stop_and_wait is not _MISSING_STOP_AND_WAIT and not callable(stop_and_wait):
        try:
            client.stop()
        except Exception:
            _reject("session_close_failed")
        _reject("session_close_method_invalid")
    if callable(stop_and_wait):
        if stop_receipt_type is None:
            try:
                client.stop()
            except Exception:
                _reject("session_close_failed")
            _reject("session_close_receipt_untrusted")
        try:
            receipt = stop_and_wait(timeout=_MAX_CLOSE_JOIN_WAIT_SECONDS)
        except Exception:
            _reject("session_close_failed")
        if stop_receipt_type is None or type(receipt) is not stop_receipt_type:
            _reject("session_close_receipt_untrusted")
        try:
            connection_generation = receipt.connection_generation
            join_required = receipt.join_required
            join_completed = receipt.join_completed
            native_released = receipt.native_released
            thread_alive = receipt.thread_alive
            timed_out = receipt.timed_out
            complete = receipt.complete
        except Exception:
            _reject("session_close_receipt_invalid")
        if (
            type(connection_generation) is not int
            or connection_generation < 0
            or (
                expected_connection_generation is not None
                and connection_generation != expected_connection_generation
            )
            or type(join_required) is not bool
            or type(join_completed) is not bool
            or type(native_released) is not bool
            or (thread_alive is not None and type(thread_alive) is not bool)
            or type(timed_out) is not bool
            or type(complete) is not bool
        ):
            _reject("session_close_receipt_invalid")
        if (
            (join_required and not join_completed and native_released)
            or (join_completed and thread_alive is not False)
            or (not join_required and thread_alive is True)
        ):
            _reject("session_close_receipt_invalid")
        expected_complete = (
            native_released
            and (not join_required or join_completed)
            and thread_alive is False
            and not timed_out
        )
        if complete is not expected_complete:
            _reject("session_close_receipt_invalid")
        if not complete:
            _reject("session_close_incomplete")
        return

    join_state_known = True
    join_thread = None
    join_active = False
    native_init_started = False
    try:
        has_join_thread = hasattr(client, "_thread")
        join_thread = getattr(client, "_thread", None)
        join_active = getattr(client, "_join_active", False)
        native_init_started = getattr(client, "_native_init_started", False)
        join_state_known = (
            has_join_thread and type(join_active) is bool and type(native_init_started) is bool
        )
        if not join_state_known:
            join_active = False
            native_init_started = False
        join_state_uncertain = (
            join_state_known and join_thread is None and (join_active or native_init_started)
        )
    except Exception:
        join_state_known = False
        join_state_uncertain = True
        join_thread = None
    try:
        client.stop()
    except Exception:
        _reject("session_close_failed")
    if not join_state_known:
        _reject("session_join_state_unknown")
    if join_thread is not None:
        try:
            join_thread.join(_MAX_CLOSE_JOIN_WAIT_SECONDS)
            if join_thread.is_alive():
                _reject("session_close_incomplete")
        except CtpSdkReadOnlyError:
            raise
        except Exception:
            _reject("session_join_state_unknown")
    if join_state_uncertain:
        _reject("session_close_incomplete")
    try:
        join_active = getattr(client, "_join_active", False)
        native_init_started = getattr(client, "_native_init_started", False)
    except Exception:
        _reject("session_join_state_unknown")
    if join_active is not False or native_init_started is not False:
        _reject("session_close_incomplete")


def _close_ctp_sdk_client_read_only_with_evidence(
    client: Any,
    *,
    stop_receipt_type: Optional[Any] = None,
    expected_connection_generation: Optional[int] = None,
) -> CtpSdkReadOnlyCloseEvidence:
    """Close once and retain only trustworthy, value-free shutdown facts."""

    unknown = CtpSdkReadOnlyCloseEvidence("unknown")
    try:
        stop_and_wait = getattr(client, "stop_and_wait", _MISSING_STOP_AND_WAIT)
    except Exception:
        try:
            client.stop()
        except Exception:
            pass
        return unknown

    if not callable(stop_and_wait) or stop_receipt_type is None:
        # Preserve the legacy best-effort teardown, but do not turn its private
        # Python thread observations into native Release/Join evidence.
        try:
            _close_ctp_sdk_client_read_only(
                client,
                stop_receipt_type=stop_receipt_type,
                expected_connection_generation=expected_connection_generation,
            )
        except Exception:
            pass
        return unknown

    try:
        receipt = stop_and_wait(timeout=_MAX_CLOSE_JOIN_WAIT_SECONDS)
    except Exception:
        return unknown
    if type(receipt) is not stop_receipt_type:
        return unknown

    try:
        connection_generation = receipt.connection_generation
        join_required = receipt.join_required
        join_completed = receipt.join_completed
        native_released = receipt.native_released
        thread_alive = receipt.thread_alive
        timed_out = receipt.timed_out
        client_stop_returned = receipt.client_stop_returned
        complete = receipt.complete
    except Exception:
        return unknown

    if (
        type(connection_generation) is not int
        or connection_generation < 0
        or (
            expected_connection_generation is not None
            and connection_generation != expected_connection_generation
        )
        or type(join_required) is not bool
        or type(join_completed) is not bool
        or type(native_released) is not bool
        or (thread_alive is not None and type(thread_alive) is not bool)
        or type(timed_out) is not bool
        or (client_stop_returned is not None and type(client_stop_returned) is not bool)
        or type(complete) is not bool
        or (join_required and not join_completed and native_released)
        or (join_completed and thread_alive is not False)
        or (not join_required and thread_alive is True)
    ):
        return unknown

    expected_complete = (
        native_released
        and (not join_required or join_completed)
        and thread_alive is False
        and not timed_out
        and client_stop_returned is True
    )
    if complete is not expected_complete:
        return unknown

    receipt_facts = {
        "native_released": native_released,
        "join_required": join_required,
        "join_completed": join_completed,
        "thread_alive": thread_alive,
        "timed_out": timed_out,
        "client_stop_returned": client_stop_returned,
    }
    if complete:
        return CtpSdkReadOnlyCloseEvidence("complete", **receipt_facts)
    if join_required and not join_completed:
        return CtpSdkReadOnlyCloseEvidence("native_join_pending", **receipt_facts)
    return CtpSdkReadOnlyCloseEvidence("unknown", **receipt_facts)


class CtpCredentialSource(Protocol):
    """A scoped resolver result; this factory never stores raw credentials."""

    def require_credential(self, name: str) -> str:
        """Return one already scoped credential value."""


@dataclass(frozen=True)
class CtpSdkReadOnlyScope:
    """The exact CTP query target selected by the sealed runtime config."""

    environment: str
    sdk_profile: str
    td_front: str
    md_front: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str

    def __post_init__(self) -> None:
        if self.environment != "simnow" or self.sdk_profile != "config_front_pair":
            raise ValueError("read-only SDK scope needs the sealed SimNow config binding")
        for name in ("td_front", "md_front"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 128
                or any(character.isspace() or ord(character) < 0x20 for character in value)
            ):
                raise ValueError("read-only SDK scope has an invalid configured front")
            try:
                parsed = urlsplit(value)
                port = parsed.port
            except ValueError:
                parsed = None
                port = None
            if (
                parsed is None
                or parsed.scheme != "tcp"
                or not parsed.hostname
                or port is None
                or not 1 <= port <= 65535
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or value != "tcp://{0}:{1}".format(parsed.hostname, port)
            ):
                raise ValueError("read-only SDK scope has an invalid configured front")
        if self.td_front == self.md_front:
            raise ValueError("read-only SDK scope needs distinct TD and MD fronts")
        if type(self.account_fingerprint_sha256) is not str or not _SHA256_RE.fullmatch(
            self.account_fingerprint_sha256
        ):
            raise ValueError("invalid code-owned account fingerprint")
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            raise ValueError("invalid code-owned instrument")
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            raise ValueError("invalid code-owned exchange")
        if type(self.hedge_flag) is not str or not _HEDGE_RE.fullmatch(self.hedge_flag):
            raise ValueError("invalid code-owned hedge flag")


def _default_sdk_components() -> Tuple[Any, ...]:
    """Load the CTP SDK inside the composition root's capability-origin fence.

    This lazy import alone does not prove an installed or release-approved wheel.
    """

    from bt_api_ctp import CtpNativeQueryCertificateBuilder
    from bt_api_ctp.ctp.client import TraderClient

    try:
        from bt_api_ctp.ctp.client import CtpNativeStopReceipt
    except ImportError:
        # Reviewed older SDKs still provide the legacy stop() surface.  Their
        # shutdown is accepted only through the conservative captured-thread
        # fallback below.
        return TraderClient, CtpNativeQueryCertificateBuilder

    if (
        type(CtpNativeStopReceipt) is not type
        or CtpNativeStopReceipt.__module__ != "bt_api_ctp.ctp.client"
        or CtpNativeStopReceipt.__name__ != "CtpNativeStopReceipt"
    ):
        raise ImportError("untrusted CTP native stop receipt type")

    return TraderClient, CtpNativeQueryCertificateBuilder, CtpNativeStopReceipt


def _deadline_remaining(valid_until: float, monotonic_deadline: float) -> float:
    wall_remaining = valid_until - time.time()
    monotonic_remaining = monotonic_deadline - time.monotonic()
    if not math.isfinite(wall_remaining) or not math.isfinite(monotonic_remaining):
        _reject("session_clock_invalid")
    remaining = min(wall_remaining, monotonic_remaining)
    if remaining <= 0:
        _reject("session_deadline_expired")
    return remaining


def _credential(source: CtpCredentialSource, name: str) -> str:
    try:
        value = source.require_credential(name)
    except Exception:
        _reject("credential_unavailable")
    if type(value) is not str or not value:
        _reject("credential_unavailable")
    if name in ("broker_id", "user_id") and not _ACCOUNT_ID_RE.fullmatch(value):
        _reject("credential_identity_invalid")
    return value


def _identity_from_client(client: Any, scope: CtpSdkReadOnlyScope) -> CtpReadOnlySessionIdentity:
    try:
        session_scope = client.get_query_session_scope()
        if session_scope.read_only_ready is not True:
            _reject("session_not_read_only_ready")
        broker_id = session_scope.broker_id
        investor_id = session_scope.investor_id
        if (
            type(broker_id) is not str
            or not _ACCOUNT_ID_RE.fullmatch(broker_id)
            or type(investor_id) is not str
            or not _ACCOUNT_ID_RE.fullmatch(investor_id)
        ):
            _reject("session_account_identity_invalid")
        digest = hashlib.sha256(
            "{0}:{1}".format(broker_id, investor_id).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(digest, scope.account_fingerprint_sha256):
            _reject("session_account_mismatch")
        front_reader = getattr(client, "get_front_binding_state", None)
        if not callable(front_reader):
            _reject("session_front_binding_unavailable")
        front_state = front_reader()
        if (
            type(front_state) is not dict
            or front_state.get("configured_front") != scope.td_front
            or front_state.get("registered_front") != scope.td_front
            or front_state.get("connection_confirmed_front") != scope.td_front
            or front_state.get("connected") is not True
            or front_state.get("native_api_current") is not True
            or front_state.get("bound_identity_current") is not True
            or front_state.get("connection_generation") != session_scope.connection_generation
        ):
            _reject("session_front_binding_mismatch")
        return CtpReadOnlySessionIdentity(
            provider="ctp",
            environment=scope.environment,
            account_fingerprint_sha256=digest,
            trading_day=session_scope.trading_day,
            connection_generation=session_scope.connection_generation,
        )
    except CtpSdkReadOnlyError:
        raise
    except Exception:
        _reject("session_identity_unavailable")


def _certificate_rate_exchange_scopes(certificate: Any) -> Tuple[Tuple[str, str], ...]:
    """Validate and retain the SDK's per-rate-query exchange-scope evidence."""

    try:
        public_reader = getattr(certificate, "as_public_dict")
        public = public_reader()
        certificate_sha256 = certificate.certificate_sha256
        query_digests = certificate.query_digests
    except Exception:
        _reject("native_rate_exchange_scope_unavailable")
    if (
        not callable(public_reader)
        or type(public) is not dict
        or public.get("schema") != _NATIVE_CERTIFICATE_SCHEMA
        or public.get("complete") is not True
        or public.get("atomic_snapshot") is not False
        or public.get("execution_authorized") is not False
        or type(public.get("queries")) is not list
        or type(query_digests) is not tuple
        or type(certificate_sha256) is not str
        or not _SHA256_RE.fullmatch(certificate_sha256)
        or public.get("certificate_sha256") != certificate_sha256
        or public.get("query_digest") != certificate_sha256
        or len(public["queries"]) != len(_QUERY_ORDER)
    ):
        _reject("native_rate_exchange_scope_invalid")

    digests_by_name = {}
    for pair in query_digests:
        if type(pair) is not tuple or len(pair) != 2:
            _reject("native_rate_exchange_scope_invalid")
        name, digest = pair
        if (
            type(name) is not str
            or name not in {query_name for query_name, _method_name in _QUERY_ORDER}
            or type(digest) is not str
            or not _SHA256_RE.fullmatch(digest)
            or name in digests_by_name
        ):
            _reject("native_rate_exchange_scope_invalid")
        digests_by_name[name] = digest
    expected_names = {query_name for query_name, _method_name in _QUERY_ORDER}
    if set(digests_by_name) != expected_names:
        _reject("native_rate_exchange_scope_invalid")

    rows_by_name = {}
    for row in public["queries"]:
        if type(row) is not dict:
            _reject("native_rate_exchange_scope_invalid")
        name = row.get("request_type")
        if (
            type(name) is not str
            or name not in expected_names
            or name in rows_by_name
            or row.get("records_sha256") != digests_by_name.get(name)
            or "rate_exchange_scope" not in row
        ):
            _reject("native_rate_exchange_scope_invalid")
        scope = row["rate_exchange_scope"]
        if name in _RATE_QUERY_NAMES:
            if type(scope) is not str or scope not in _RATE_EXCHANGE_SCOPE_VALUES:
                _reject("native_rate_exchange_scope_invalid")
        elif scope is not None:
            _reject("native_rate_exchange_scope_invalid")
        rows_by_name[name] = scope
    if set(rows_by_name) != expected_names:
        _reject("native_rate_exchange_scope_invalid")
    return tuple(sorted((_SNAPSHOT_NAMES[name], rows_by_name[name]) for name in _RATE_QUERY_NAMES))


class _CtpSdkReadOnlySession:
    """Minimal wrapper hiding the native client's write-capable methods."""

    def __init__(
        self,
        client: Any,
        scope: CtpSdkReadOnlyScope,
        builder_type: Any,
        stop_receipt_type: Optional[Any],
        connection_generation: int,
        valid_until: float,
        monotonic_deadline: float,
        query_timeout: float,
    ) -> None:
        self._client = client
        self._scope = CtpSdkReadOnlyScope(
            environment=scope.environment,
            sdk_profile=scope.sdk_profile,
            td_front=scope.td_front,
            md_front=scope.md_front,
            account_fingerprint_sha256=scope.account_fingerprint_sha256,
            instrument_id=scope.instrument_id,
            exchange_id=scope.exchange_id,
            hedge_flag=scope.hedge_flag,
        )
        self._builder_type = builder_type
        self._stop_receipt_type = stop_receipt_type
        self._connection_generation = connection_generation
        self._valid_until = valid_until
        self._monotonic_deadline = monotonic_deadline
        self._query_timeout = query_timeout
        self._closed = False
        self._close_complete = False
        self._close_evidence: Optional[CtpSdkReadOnlyCloseEvidence] = None

    def _require_open(self) -> float:
        if self._closed:
            _reject("session_closed")
        return _deadline_remaining(self._valid_until, self._monotonic_deadline)

    def _require_zero_writes(self) -> None:
        try:
            counts = self._client.get_request_counts()
            if type(counts) is not dict or any(
                type(counts.get(name)) is not int or counts[name] != 0
                for name in _WRITE_REQUEST_KEYS
            ):
                _reject("native_write_detected")
        except CtpSdkReadOnlyError:
            raise
        except Exception:
            _reject("native_write_counts_unavailable")

    def read_identity(self) -> CtpReadOnlySessionIdentity:
        self._require_open()
        identity = _identity_from_client(self._client, self._scope)
        self._require_zero_writes()
        self._require_open()
        return identity

    def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
        first_identity = self.read_identity()
        try:
            builder = self._builder_type(
                self._client,
                instrument_id=self._scope.instrument_id,
                exchange_id=self._scope.exchange_id,
                hedge_flag=self._scope.hedge_flag,
            )
            for query_name, method_name in _QUERY_ORDER:
                remaining = self._require_open()
                method = getattr(self._client, method_name)
                timeout = min(remaining, self._query_timeout)
                if query_name == "instruments":
                    result = method(
                        instrument_id=self._scope.instrument_id,
                        exchange_id=self._scope.exchange_id,
                        timeout=timeout,
                    )
                elif query_name == "margin_rate":
                    result = method(
                        self._scope.instrument_id,
                        exchange_id=self._scope.exchange_id,
                        hedge_flag=self._scope.hedge_flag,
                        timeout=timeout,
                    )
                elif query_name == "commission_rate":
                    result = method(
                        self._scope.instrument_id,
                        exchange_id=self._scope.exchange_id,
                        timeout=timeout,
                    )
                else:
                    result = method(timeout=timeout)
                # A result is checked immediately, within its SDK-issued TTL.
                builder.add(result)
                self._require_zero_writes()
                self._require_open()
            certificate = builder.finish()
            final_identity = self.read_identity()
            if final_identity != first_identity:
                _reject("session_identity_changed")
            query_digests = tuple(
                (_SNAPSHOT_NAMES.get(name, name), digest)
                for name, digest in certificate.query_digests
            )
            rate_exchange_scopes = _certificate_rate_exchange_scopes(certificate)
            return CtpReadOnlyQuerySnapshot.from_query_digests(
                first_identity,
                query_digests,
                native_certificate_sha256=certificate.certificate_sha256,
                rate_exchange_scopes=rate_exchange_scopes,
            )
        except CtpSdkReadOnlyError:
            raise
        except Exception:
            _reject("native_query_certificate_failed")

    def close_read_only(self) -> None:
        if self._closed:
            if not self._close_complete:
                _reject("session_close_incomplete")
            return
        self._closed = True
        # The legacy API intentionally exposes no receipt details.  If a
        # caller later asks for the projection, do not repeat native stop.
        self._close_evidence = CtpSdkReadOnlyCloseEvidence("unknown")
        _close_ctp_sdk_client_read_only(
            self._client,
            stop_receipt_type=self._stop_receipt_type,
            expected_connection_generation=self._connection_generation,
        )
        self._close_complete = True

    def close_read_only_with_evidence(self) -> CtpSdkReadOnlyCloseEvidence:
        """Close once and return a strict, value-free native stop projection.

        Unlike ``close_read_only``, this method returns incomplete or unknown
        outcomes so an outer Job supervisor can terminate and classify the
        child.  It never retries a stop attempt.  Callers must accept only
        ``verified_complete``; unknown evidence is not a successful close.
        """

        if self._close_evidence is not None:
            return self._close_evidence
        if self._closed:
            return CtpSdkReadOnlyCloseEvidence("unknown")
        self._closed = True
        try:
            self._close_evidence = _close_ctp_sdk_client_read_only_with_evidence(
                self._client,
                stop_receipt_type=self._stop_receipt_type,
                expected_connection_generation=self._connection_generation,
            )
        except Exception:
            self._close_evidence = CtpSdkReadOnlyCloseEvidence("unknown")
        self._close_complete = self._close_evidence.verified_complete
        return self._close_evidence


class CtpSdkReadOnlySessionFactory:
    """A single-session native factory with no trading-write interface."""

    def __init__(
        self,
        scope: CtpSdkReadOnlyScope,
        credential_source: CtpCredentialSource,
        *,
        connect_timeout: float = 15.0,
        query_timeout: float = 5.0,
        sdk_components_loader: Optional[Callable[[], Tuple[Any, ...]]] = None,
    ) -> None:
        if type(scope) is not CtpSdkReadOnlyScope:
            raise TypeError("scope must be a CtpSdkReadOnlyScope")
        if type(connect_timeout) not in (int, float) or not 0 < connect_timeout <= 60:
            raise ValueError("invalid read-only connect timeout")
        if type(query_timeout) not in (int, float) or not 0 < query_timeout <= 30:
            raise ValueError("invalid read-only query timeout")
        self._scope = CtpSdkReadOnlyScope(
            environment=scope.environment,
            sdk_profile=scope.sdk_profile,
            td_front=scope.td_front,
            md_front=scope.md_front,
            account_fingerprint_sha256=scope.account_fingerprint_sha256,
            instrument_id=scope.instrument_id,
            exchange_id=scope.exchange_id,
            hedge_flag=scope.hedge_flag,
        )
        self._credential_source = credential_source
        self._connect_timeout = float(connect_timeout)
        self._query_timeout = float(query_timeout)
        self._sdk_components_loader = sdk_components_loader or _default_sdk_components

    def __repr__(self) -> str:
        return "CtpSdkReadOnlySessionFactory(environment={0!r}, credentials=<redacted>)".format(
            self._scope.environment
        )

    def open_read_only(self, request: CtpReadOnlySessionRequest) -> _CtpSdkReadOnlySession:
        if type(request) is not CtpReadOnlySessionRequest:
            raise TypeError("request must be a CtpReadOnlySessionRequest")
        if request.provider != "ctp" or request.environment != self._scope.environment:
            _reject("environment_mismatch")
        if not hmac.compare_digest(
            request.account_fingerprint_sha256,
            self._scope.account_fingerprint_sha256,
        ):
            _reject("account_mismatch")
        remaining = request.valid_until - time.time()
        if not math.isfinite(remaining):
            _reject("session_clock_invalid")
        if remaining <= 0:
            _reject("session_deadline_expired")
        monotonic_deadline = time.monotonic() + remaining
        _deadline_remaining(request.valid_until, monotonic_deadline)

        broker_id = _credential(self._credential_source, "broker_id")
        user_id = _credential(self._credential_source, "user_id")
        account_digest = hashlib.sha256(
            "{0}:{1}".format(broker_id, user_id).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(account_digest, self._scope.account_fingerprint_sha256):
            _reject("credential_account_mismatch")
        password = _credential(self._credential_source, "password")
        app_id = _credential(self._credential_source, "app_id")
        auth_code = _credential(self._credential_source, "auth_code")
        _deadline_remaining(request.valid_until, monotonic_deadline)

        client = None
        stop_receipt_type = None
        connection_generation = None
        session = None
        open_error = None
        opened = False
        try:
            components = self._sdk_components_loader()
            if type(components) is not tuple or len(components) not in (2, 3):
                _reject("sdk_components_invalid")
            client_type, builder_type = components[:2]
            if len(components) == 3:
                stop_receipt_type = components[2]
                if not isinstance(stop_receipt_type, type):
                    _reject("sdk_components_invalid")
            client = client_type(
                self._scope.td_front,
                broker_id,
                user_id,
                password,
                app_id=app_id,
                auth_code=auth_code,
                auto_settlement_confirm=False,
            )
            client.start(block=False)
            remaining = _deadline_remaining(request.valid_until, monotonic_deadline)
            if client.wait_ready(timeout=min(remaining, self._connect_timeout)) is not True:
                _reject("session_not_read_only_ready")
            _deadline_remaining(request.valid_until, monotonic_deadline)
            if client.get_session_state().get("auto_settlement_confirm") is not False:
                _reject("settlement_write_not_disabled")
            identity = _identity_from_client(client, self._scope)
            connection_generation = identity.connection_generation
            session = _CtpSdkReadOnlySession(
                client,
                self._scope,
                builder_type,
                stop_receipt_type,
                connection_generation,
                request.valid_until,
                monotonic_deadline,
                self._query_timeout,
            )
            session._require_zero_writes()
            opened = True
        except CtpSdkReadOnlyError as exc:
            open_error = exc
        except Exception:
            open_error = CtpSdkReadOnlyError("session_open_failed")
        if not opened and client is not None:
            try:
                _close_ctp_sdk_client_read_only(
                    client,
                    stop_receipt_type=stop_receipt_type,
                    expected_connection_generation=connection_generation,
                )
            except CtpSdkReadOnlyError as cleanup_error:
                if open_error is None:
                    open_error = cleanup_error
                else:
                    open_error = CtpSdkReadOnlyError(
                        open_error.reason,
                        cleanup_reason=cleanup_error.reason,
                    )
        if open_error is not None:
            raise open_error from None
        if not opened or session is None:
            _reject("session_open_failed")
        return session


__all__ = [
    "CtpCredentialSource",
    "CtpSdkReadOnlyError",
    "CtpSdkReadOnlyCloseEvidence",
    "CtpSdkReadOnlyScope",
    "CtpSdkReadOnlySessionFactory",
]
