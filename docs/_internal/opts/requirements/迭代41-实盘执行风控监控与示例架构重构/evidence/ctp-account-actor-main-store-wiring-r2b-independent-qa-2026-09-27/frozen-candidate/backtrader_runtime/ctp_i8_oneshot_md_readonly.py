"""Offline-adaptable I8 MD-only identity-unverified one-shot protocol.

This adapter accepts only the I8 SDK client's fixed login-ID-zero callback,
submits the single sealed-config instrument after the explicit
``on_identity_unverified`` callback, and requires its matching final
subscription acknowledgement, same-trading-day first tick, and complete
native stop receipt. It creates no Trader or execution client.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .ctp_i3_oneshot_md_readonly import (
    _close_client,
    _require_i3_sdk_types,
)
from .ctp_sdk_market_readonly import (
    _AccountLease,
    _account_lock_key,
    _field_text,
    _md_client_snapshot,
    _read_credential,
    _reject,
    _timeout,
    _valid_tick,
    _validated_admission,
    CtpMarketCredentialSource,
    CtpSdkMarketReadOnlyError,
)


_I8_CALLBACK_DISPOSITION = "identity_unverified"
_I8_CALLBACK_NATIVE_SHAPE = "empty"
_I8_CLOSE_STATES = frozenset(
    {
        "not_started",
        "native_stop_method_unknown",
        "stop_failed",
        "native_stop_receipt_unknown",
        "native_stop_receipt_inconsistent",
        "native_join_state_unknown",
        "native_join_pending",
        "native_stop_incomplete",
        "stop_returned",
    }
)
_I8_PRIMARY_ERRORS = frozenset(
    {
        "admission_invalid",
        "credential_account_mismatch",
        "probe_deadline_expired",
        "market_client_type_required",
        "market_client_state_unavailable",
        "market_front_binding_mismatch",
        "market_client_identity_mismatch",
        "market_login_identity_mismatch",
        "market_subscription_rejected",
        "market_front_disconnected",
        "market_probe_failed",
        "market_login_timeout",
        "subscription_ack_timeout",
        "matching_tick_not_observed",
        "market_observation_incomplete",
    }
)
_I8_ERROR_REASONS = _I8_PRIMARY_ERRORS | {"market_client_stop_failed"}
_I8_LOGIN_DISPOSITIONS = frozenset(
    {
        "none",
        "stale_spi",
        "generation_mismatch",
        "request_id_type_invalid",
        "request_id_mismatch",
        "nonterminal",
        "accepted",
        "identity_unverified",
        "provider_rejected",
        "identity_rejected",
        "terminal",
    }
)
_I8_REQUEST_RELATIONS = frozenset({"not_observed", "invalid", "zero", "lower", "equal", "higher"})
_I8_RESPONSE_STATUSES = frozenset({"not_observed", "missing", "invalid", "zero", "nonzero"})
_I8_LOGIN_ID_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_I8_TRADING_DAY_SHAPES = frozenset(
    {"not_observed", "unreadable", "empty", "invalid_format", "invalid_calendar", "valid"}
)
_I8_NATIVE_SHAPES = frozenset(
    {"not_observed", "unreadable", "empty", "nonempty_terminated", "unterminated"}
)


@dataclass(frozen=True)
class CtpI8OneShotMdDiagnosticEvidence:
    """Value-free, bounded evidence retained when an I8 probe raises.

    Boolean ``True`` values report only positively captured progress. ``None``
    means the event was unavailable or not safely established; partial
    evidence never treats a missing observation as proof of absence.
    """

    evidence_level: str
    close_state: str
    primary_error: str | None
    login_callback_count: str
    login_callback_disposition: str
    login_request_id_relation: str
    login_response_error_status: str
    login_broker_id_shape: str
    login_user_id_shape: str
    login_trading_day_shape: str
    native_broker_id_shape: str
    native_user_id_shape: str
    identity_unverified: bool | None
    subscription_acknowledged: bool | None
    matching_tick_observed: bool | None
    same_trading_day_observed: bool | None
    client_stop_returned: bool | None
    native_join_pending: bool | None


@dataclass(frozen=True)
class CtpI8OneShotMdObservation:
    """Exact, value-free observation from one I8 MD client."""

    md_front_sha256: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    connection_generation: int
    identity_unverified: bool
    market_login_ready: bool
    subscription_acknowledged: bool
    matching_tick_observed: bool
    same_trading_day_observed: bool
    client_stop_returned: bool
    native_join_pending: bool
    diagnostic_evidence: CtpI8OneShotMdDiagnosticEvidence | None = None

    @property
    def probe_session_closed(self) -> bool:
        return self.client_stop_returned and not self.native_join_pending

    @property
    def order_submission_authorized(self) -> bool:
        return False

    @property
    def trading_writes(self) -> int:
        return 0

    @property
    def settlement_writes(self) -> int:
        return 0


def _i8_login_diagnostic(client: Any) -> tuple[int, str, str, str, str, str, str] | None:
    """Read the exact I8 bounded login identity shape without copying IDs."""

    try:
        diagnostic = client.login_callback_diagnostic
        count = diagnostic.callback_count
        disposition = diagnostic.disposition.value
        request_relation = diagnostic.request_id_relation.value
        response_status = diagnostic.response_error_status.value
        broker_shape = diagnostic.native_broker_id_shape.value
        user_shape = diagnostic.native_user_id_shape.value
        trading_day_shape = diagnostic.trading_day_shape.value
    except Exception:
        return None
    values = (
        disposition,
        request_relation,
        response_status,
        broker_shape,
        user_shape,
        trading_day_shape,
    )
    if type(count) is not int or count != 1 or any(type(value) is not str for value in values):
        return None
    return (count, *values)


def _i8_enum_value(diagnostic: Any, field_name: str, allowed: frozenset[str]) -> str:
    try:
        value = getattr(getattr(diagnostic, field_name), "value")
    except Exception:
        return "unavailable"
    if type(value) is str and value in allowed:
        return value
    return "unavailable"


def _i8_callback_evidence(client: Any) -> tuple[str, ...]:
    """Copy only bounded SDK enum/count classifications; never retain payloads."""

    try:
        diagnostic = client.login_callback_diagnostic
    except Exception:
        diagnostic = None
    count_value = None
    if diagnostic is not None:
        try:
            candidate = diagnostic.callback_count
        except Exception:
            candidate = None
        if type(candidate) is int and 0 <= candidate <= 1_000_000:
            count_value = "zero" if candidate == 0 else "one" if candidate == 1 else "multiple"
    if diagnostic is None:
        return (
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
            "unavailable",
        )
    return (
        count_value or "unavailable",
        _i8_enum_value(diagnostic, "disposition", _I8_LOGIN_DISPOSITIONS),
        _i8_enum_value(diagnostic, "request_id_relation", _I8_REQUEST_RELATIONS),
        _i8_enum_value(diagnostic, "response_error_status", _I8_RESPONSE_STATUSES),
        _i8_enum_value(diagnostic, "broker_id_shape", _I8_LOGIN_ID_SHAPES),
        _i8_enum_value(diagnostic, "user_id_shape", _I8_LOGIN_ID_SHAPES),
        _i8_enum_value(diagnostic, "trading_day_shape", _I8_TRADING_DAY_SHAPES),
        _i8_enum_value(diagnostic, "native_broker_id_shape", _I8_NATIVE_SHAPES),
        _i8_enum_value(diagnostic, "native_user_id_shape", _I8_NATIVE_SHAPES),
    )


def _i8_progress_evidence(condition: threading.Condition, state: dict[str, Any]) -> dict[str, bool]:
    """Snapshot only adapter-confirmed positive progress, never inferred negatives."""

    with condition:
        return {
            "identity_unverified": state.get("identity") is True,
            "subscription_acknowledged": state.get("acknowledged") is True,
            "matching_tick_observed": state.get("tick") is True,
            "same_trading_day_observed": state.get("same_trading_day") is True,
        }


def _i8_make_evidence(
    *,
    evidence_level: str,
    close_state: Any,
    primary_error: Any,
    callback: tuple[str, ...],
    progress: dict[str, bool],
    client_stop_returned: Any,
) -> CtpI8OneShotMdDiagnosticEvidence:
    safe_close_state = (
        close_state
        if type(close_state) is str and close_state in _I8_CLOSE_STATES
        else "unavailable"
    )
    safe_primary_error = (
        None
        if primary_error is None
        else primary_error
        if type(primary_error) is str and primary_error in _I8_PRIMARY_ERRORS
        else "unavailable"
    )
    safe_stop_returned = client_stop_returned if type(client_stop_returned) is bool else None
    if safe_close_state == "native_join_pending":
        join_pending: bool | None = True
    elif safe_close_state == "stop_returned":
        join_pending = False
    else:
        join_pending = None
    safe_progress = {
        name: True if progress.get(name) is True else None
        for name in (
            "identity_unverified",
            "subscription_acknowledged",
            "matching_tick_observed",
            "same_trading_day_observed",
        )
    }
    safe_callback = callback if len(callback) == 9 else ("unavailable",) * 9
    return CtpI8OneShotMdDiagnosticEvidence(
        evidence_level=evidence_level,
        close_state=safe_close_state,
        primary_error=safe_primary_error,
        login_callback_count=safe_callback[0],
        login_callback_disposition=safe_callback[1],
        login_request_id_relation=safe_callback[2],
        login_response_error_status=safe_callback[3],
        login_broker_id_shape=safe_callback[4],
        login_user_id_shape=safe_callback[5],
        login_trading_day_shape=safe_callback[6],
        native_broker_id_shape=safe_callback[7],
        native_user_id_shape=safe_callback[8],
        identity_unverified=safe_progress["identity_unverified"],
        subscription_acknowledged=safe_progress["subscription_acknowledged"],
        matching_tick_observed=safe_progress["matching_tick_observed"],
        same_trading_day_observed=safe_progress["same_trading_day_observed"],
        client_stop_returned=safe_stop_returned,
        native_join_pending=join_pending,
    )


def _safe_i8_primary_reason(value: Any) -> str | None:
    if value is None:
        return None
    if type(value) is str and value in _I8_PRIMARY_ERRORS:
        return value
    return "unavailable"


def _reject_with_i8_evidence(
    reason: str,
    *,
    evidence: CtpI8OneShotMdDiagnosticEvidence,
    close_state: str,
    primary_reason: str | None,
    client_stop_returned: bool | None,
) -> None:
    safe_reason = (
        reason if type(reason) is str and reason in _I8_ERROR_REASONS else "market_probe_failed"
    )
    safe_stop_returned = client_stop_returned if type(client_stop_returned) is bool else None
    try:
        _reject(
            safe_reason,
            close_state=evidence.close_state,
            primary_reason=_safe_i8_primary_reason(primary_reason),
            client_stop_returned=safe_stop_returned,
        )
    except CtpSdkMarketReadOnlyError as error:
        error.i8_diagnostic_evidence = evidence
        raise


def _identity_unverified_day(client: Any) -> str | None:
    try:
        state_lock = client._state_lock
        with state_lock:
            trading_day = client._diagnostic_identity_unverified_trading_day
    except Exception:
        return None
    if type(trading_day) is not str or len(trading_day) != 8 or not trading_day.isascii():
        return None
    try:
        datetime.strptime(trading_day, "%Y%m%d")
    except ValueError:
        return None
    return trading_day


def _valid_identity_unverified_callback(
    client: Any,
    *,
    front: str,
    broker_id: str,
    user_id: str,
    initial_generation: int,
) -> tuple[int, str] | None:
    snapshot = _md_client_snapshot(client)
    diagnostic = _i8_login_diagnostic(client)
    day = _identity_unverified_day(client)
    if (
        snapshot is None
        or diagnostic is None
        or day is None
        or snapshot[0] != front
        or snapshot[1] != broker_id
        or snapshot[2] != user_id
        or snapshot[3] <= initial_generation
        or snapshot[4] is not True
        or snapshot[5] is not False
        or client.diagnostic_identity_unverified is not True
        or client.active_md_identity is not None
        or client.is_ready is not False
        or diagnostic[1] != _I8_CALLBACK_DISPOSITION
        or diagnostic[2] != "zero"
        or diagnostic[3] != "zero"
        or diagnostic[4] != _I8_CALLBACK_NATIVE_SHAPE
        or diagnostic[5] != _I8_CALLBACK_NATIVE_SHAPE
        or diagnostic[6] != "valid"
    ):
        return None
    return snapshot[3], day


def probe_i8_oneshot_md_readonly(
    *,
    admission: Any,
    credential_source: CtpMarketCredentialSource,
    client_type: Any,
    stop_receipt_type: Any,
    expected_diagnostic_instrument: str,
    timeout_seconds: float = 15.0,
) -> CtpI8OneShotMdObservation:
    """Run one strict identity-unverified MD observation on injected SDK types."""

    admitted = _validated_admission(admission)
    _require_i3_sdk_types(client_type, stop_receipt_type)
    timeout = _timeout(timeout_seconds)
    if (
        type(expected_diagnostic_instrument) is not str
        or expected_diagnostic_instrument != admitted.instrument_id
    ):
        _reject("admission_invalid")

    front = admitted.md_front
    instrument = admitted.instrument_id
    exchange = admitted.exchange_id
    deadline = time.monotonic() + timeout
    lease = _AccountLease(_account_lock_key(admitted.account_fingerprint_sha256))
    lease.acquire()

    client = None
    close_state = "not_started"
    client_stop_returned: bool | None = None
    close_complete = False
    callback_evidence = ("unavailable",) * 9
    progress_evidence = {
        "identity_unverified": False,
        "subscription_acknowledged": False,
        "matching_tick_observed": False,
        "same_trading_day_observed": False,
    }
    evidence_level = "unavailable"
    primary_error: str | None = None
    connection_generation: int | None = None
    same_trading_day_observed = False
    condition = threading.Condition()
    state: dict[str, Any] = {
        "acknowledged": False,
        "closed": False,
        "error": None,
        "identity": False,
        "login_callback_count": 0,
        "login_generation": None,
        "subscription_submitted": False,
        "tick": False,
        "trading_day": None,
    }

    try:
        broker_id = _read_credential(credential_source, "broker_id")
        user_id = _read_credential(credential_source, "user_id")
        password = _read_credential(credential_source, "password")
        account_digest = hashlib.sha256(
            "{0}:{1}".format(broker_id, user_id).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(account_digest, admitted.account_fingerprint_sha256):
            _reject("credential_account_mismatch")
        if time.monotonic() >= deadline:
            _reject("probe_deadline_expired")

        client = client_type(
            front,
            broker_id,
            user_id,
            password,
            expected_diagnostic_instrument=instrument,
        )
        if type(client) is not client_type:
            _reject("market_client_type_required")
        initial_snapshot = _md_client_snapshot(client)
        if initial_snapshot is None:
            _reject("market_client_state_unavailable")
        if initial_snapshot[0] != front:
            _reject("market_front_binding_mismatch")
        if initial_snapshot[1] != broker_id or initial_snapshot[2] != user_id:
            _reject("market_client_identity_mismatch")
        initial_generation = initial_snapshot[3]

        def record_error(reason: str) -> None:
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["error"] = reason
                    condition.notify_all()

        def on_identity_unverified() -> None:
            with condition:
                state["login_callback_count"] += 1
                callback_count = state["login_callback_count"]
            identity_state = _valid_identity_unverified_callback(
                client,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
                initial_generation=initial_generation,
            )
            if callback_count != 1 or identity_state is None:
                record_error("market_login_identity_mismatch")
                return
            generation, trading_day = identity_state
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                state["identity"] = True
                state["login_generation"] = generation
                state["trading_day"] = trading_day
                state["subscription_submitted"] = True
                condition.notify_all()
            result = client.subscribe(instrument)
            if type(result) is not int or result != 0:
                record_error("market_subscription_rejected")

        def on_login(_login_field: Any) -> None:
            # I8 must use the explicit unverified callback and stay logged out.
            record_error("market_login_identity_mismatch")

        def on_error(_response: Any) -> None:
            with condition:
                reason = (
                    "market_login_identity_mismatch"
                    if not state["identity"]
                    else "market_subscription_rejected"
                    if not state["acknowledged"]
                    else "market_probe_failed"
                )
            record_error(reason)

        def on_disconnect(_reason: Any) -> None:
            record_error("market_front_disconnected")

        def on_subscribe(specific_instrument: Any, response: Any) -> None:
            with condition:
                generation = state["login_generation"]
                was_submitted = state["subscription_submitted"]
                already_acknowledged = state["acknowledged"]
            snapshot = _md_client_snapshot(client)
            try:
                error_id = response.ErrorID
            except Exception:
                error_id = None
            if (
                not was_submitted
                or generation is None
                or already_acknowledged
                or _field_text(specific_instrument, "InstrumentID") != instrument
                or type(error_id) is not int
                or error_id != 0
                or snapshot is None
                or snapshot[3] != generation
                or snapshot[0] != front
                or snapshot[4] is not True
                or snapshot[5] is not False
                or client.diagnostic_subscription_acknowledged is not True
            ):
                record_error("market_subscription_rejected")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["acknowledged"] = True
                    condition.notify_all()

        def on_tick(tick: Any) -> None:
            with condition:
                generation = state["login_generation"]
                expected_day = state["trading_day"]
                acknowledged = state["acknowledged"]
                already_observed = state["tick"]
            snapshot = _md_client_snapshot(client)
            tick_day = _field_text(tick, "TradingDay")
            flags_match = False
            try:
                with client._state_lock:
                    flags_match = (
                        client.diagnostic_terminal is True
                        and client.diagnostic_terminal_reason == "diagnostic_complete"
                        and client.diagnostic_subscription_acknowledged is True
                        and client.diagnostic_first_tick_received is True
                        and client._diagnostic_identity_unverified is True
                        and client._diagnostic_identity_unverified_active is False
                        and client._loggedin is False
                        and client._active_md_identity is None
                    )
            except Exception:
                flags_match = False
            if (
                not acknowledged
                or generation is None
                or already_observed
                or snapshot is None
                or snapshot[0] != front
                or snapshot[1] != broker_id
                or snapshot[2] != user_id
                or snapshot[3] != generation
                or snapshot[4] is not False
                or snapshot[5] is not False
                or expected_day is None
                or tick_day != expected_day
                or not flags_match
                or not _valid_tick(tick, instrument, exchange)
            ):
                record_error("market_probe_failed")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["tick"] = True
                    state["same_trading_day"] = True
                    condition.notify_all()

        client.on_identity_unverified = on_identity_unverified
        client.on_login = on_login
        client.on_error = on_error
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_tick = on_tick
        client.start(block=False)

        with condition:
            while not (state["identity"] and state["acknowledged"] and state["tick"]):
                if state["error"] is not None:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if not state["identity"]:
                        _reject("market_login_timeout")
                    _reject(
                        "subscription_ack_timeout"
                        if not state["acknowledged"]
                        else "matching_tick_not_observed"
                    )
                condition.wait(remaining)
            if state["error"] is not None:
                _reject(state["error"])
            state["closed"] = True
            connection_generation = state["login_generation"]
            same_trading_day_observed = state.get("same_trading_day") is True
    except CtpSdkMarketReadOnlyError as error:
        primary_error = error.reason
    except Exception:
        # SDK exceptions can include raw provider values; preserve no text.
        primary_error = "market_probe_failed"
    finally:
        if client is None:
            lease.release()
        else:
            with condition:
                state["closed"] = True
            callback_evidence = _i8_callback_evidence(client)
            progress_evidence = _i8_progress_evidence(condition, state)
            evidence_level = "partial"
            close_state, client_stop_returned, close_complete = _close_client(
                client,
                lease=lease,
                stop_receipt_type=stop_receipt_type,
            )

    if not close_complete:
        evidence = _i8_make_evidence(
            evidence_level=evidence_level,
            close_state=close_state,
            primary_error=primary_error,
            callback=callback_evidence,
            progress=progress_evidence,
            client_stop_returned=client_stop_returned,
        )
        _reject_with_i8_evidence(
            "market_client_stop_failed",
            evidence=evidence,
            close_state=close_state,
            primary_reason=primary_error,
            client_stop_returned=client_stop_returned,
        )
    if primary_error is not None:
        evidence = _i8_make_evidence(
            evidence_level=evidence_level,
            close_state=close_state,
            primary_error=primary_error,
            callback=callback_evidence,
            progress=progress_evidence,
            client_stop_returned=client_stop_returned,
        )
        _reject_with_i8_evidence(
            primary_error,
            evidence=evidence,
            close_state=close_state,
            primary_reason=primary_error,
            client_stop_returned=client_stop_returned,
        )
    if type(connection_generation) is not int or not same_trading_day_observed:
        evidence = _i8_make_evidence(
            evidence_level=evidence_level,
            close_state=close_state,
            primary_error=None,
            callback=callback_evidence,
            progress=progress_evidence,
            client_stop_returned=client_stop_returned,
        )
        _reject_with_i8_evidence(
            "market_observation_incomplete",
            evidence=evidence,
            close_state=close_state,
            primary_reason=None,
            client_stop_returned=client_stop_returned,
        )
    evidence = _i8_make_evidence(
        evidence_level="complete",
        close_state=close_state,
        primary_error=None,
        callback=callback_evidence,
        progress=progress_evidence,
        client_stop_returned=client_stop_returned,
    )
    return CtpI8OneShotMdObservation(
        md_front_sha256=hashlib.sha256(front.encode("utf-8")).hexdigest(),
        account_fingerprint_sha256=admitted.account_fingerprint_sha256,
        instrument_id=instrument,
        exchange_id=exchange,
        connection_generation=connection_generation,
        identity_unverified=True,
        market_login_ready=False,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
        client_stop_returned=client_stop_returned,
        native_join_pending=False,
        diagnostic_evidence=evidence,
    )


__all__ = [
    "CtpI8OneShotMdDiagnosticEvidence",
    "CtpI8OneShotMdObservation",
    "probe_i8_oneshot_md_readonly",
]
