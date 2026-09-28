"""Unregistered I10 one-shot, market-data-only observation adapter.

The injected I10 ``OneShotMdDiagnosticClient`` can report either an exact
verified login callback or the older identity-unverified diagnostic callback.
This adapter distinguishes those outcomes, then requires one exact
subscription acknowledgement, a same-trading-day tick, and a complete native
stop receipt. It does not establish account or trading readiness and exposes
no Trader or execution path.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .ctp_i3_oneshot_md_readonly import _close_client
from .ctp_sdk_market_readonly import (
    _AccountLease,
    _MD_LOGIN_BROKER_ID_SHAPES,
    _MD_LOGIN_NATIVE_FIELD_SHAPES,
    _MD_LOGIN_TRADING_DAY_SHAPES,
    _MD_LOGIN_USER_ID_SHAPES,
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


_I10_SDK_MODULE = "bt_api_ctp.ctp.client"
_I10_CLIENT_NAME = "OneShotMdDiagnosticClient"
_I10_STOP_RECEIPT_NAME = "CtpNativeStopReceipt"
_VERIFIED_SHAPES = (
    "exact_match",
    "exact_match",
    "valid",
    "nonempty_terminated",
    "nonempty_terminated",
)
_UNVERIFIED_SHAPES = ("empty", "empty", "valid", "empty", "empty")


@dataclass(frozen=True)
class CtpI10OneShotMdProgressEvidence:
    """Redacted callback progress suitable for a failure receipt.

    ``None`` means that the corresponding fact was not positively confirmed.
    This deliberately carries no account, instrument, provider, or callback
    payload values; shutdown and native Join uncertainty remain separate.
    """

    login_identity_state: str | None = None
    subscription_acknowledged: bool | None = None
    matching_tick_observed: bool | None = None
    same_trading_day_observed: bool | None = None

    def __post_init__(self) -> None:
        if self.login_identity_state is not None and (
            type(self.login_identity_state) is not str
            or self.login_identity_state not in {"verified", "identity_unverified"}
        ):
            raise ValueError("invalid I10 login identity progress")
        for value in (
            self.subscription_acknowledged,
            self.matching_tick_observed,
            self.same_trading_day_observed,
        ):
            if value is not None and type(value) is not bool:
                raise ValueError("invalid I10 callback progress")
        if self.subscription_acknowledged is True and self.login_identity_state is None:
            raise ValueError("I10 subscription progress requires confirmed login")
        if self.matching_tick_observed is True and (
            self.subscription_acknowledged is not True or self.same_trading_day_observed is not True
        ):
            raise ValueError("I10 tick progress requires confirmed ACK and trading day")
        if self.same_trading_day_observed is True and self.matching_tick_observed is not True:
            raise ValueError("I10 trading-day progress requires a matching tick")


@dataclass(frozen=True)
class CtpI10OneShotMdObservation:
    """Closed, exact-contract observation with the login identity outcome."""

    md_front_sha256: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    connection_generation: int
    login_identity_state: str
    subscription_acknowledged: bool
    matching_tick_observed: bool
    same_trading_day_observed: bool
    client_stop_returned: bool
    native_join_pending: bool

    @property
    def verified_login_observed(self) -> bool:
        return self.login_identity_state == "verified"

    @property
    def identity_unverified(self) -> bool:
        return self.login_identity_state == "identity_unverified"

    @property
    def market_login_ready(self) -> bool:
        """The adapter records login identity evidence, not readiness."""

        return False

    @property
    def account_ready(self) -> bool:
        return False

    @property
    def trading_ready(self) -> bool:
        return False

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


def _require_i10_sdk_types(client_type: Any, stop_receipt_type: Any) -> None:
    if (
        type(client_type) is not type
        or client_type.__name__ != _I10_CLIENT_NAME
        or client_type.__module__ != _I10_SDK_MODULE
        or type(stop_receipt_type) is not type
        or stop_receipt_type.__name__ != _I10_STOP_RECEIPT_NAME
        or stop_receipt_type.__module__ != _I10_SDK_MODULE
    ):
        _reject("market_client_type_required")


def _diagnostic(client: Any) -> tuple[Any, ...] | None:
    """Copy bounded SDK enums and shapes, never raw login or provider values."""

    try:
        value = client.login_callback_diagnostic
        count = value.callback_count
        disposition = value.disposition.value
        request_relation = value.request_id_relation.value
        response_status = value.response_error_status.value
        shapes = (
            value.broker_id_shape.value,
            value.user_id_shape.value,
            value.trading_day_shape.value,
            value.native_broker_id_shape.value,
            value.native_user_id_shape.value,
        )
    except Exception:
        return None
    if (
        type(count) is not int
        or not 0 <= count <= 1_000_000
        or type(disposition) is not str
        or type(request_relation) is not str
        or type(response_status) is not str
        or any(type(shape) is not str for shape in shapes)
        or shapes[0] not in _MD_LOGIN_BROKER_ID_SHAPES
        or shapes[1] not in _MD_LOGIN_USER_ID_SHAPES
        or shapes[2] not in _MD_LOGIN_TRADING_DAY_SHAPES
        or shapes[3] not in _MD_LOGIN_NATIVE_FIELD_SHAPES
        or shapes[4] not in _MD_LOGIN_NATIVE_FIELD_SHAPES
    ):
        return None
    return count, disposition, request_relation, response_status, *shapes


def _valid_day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _identity_snapshot(client: Any) -> tuple[Any, ...] | None:
    """Capture the one-shot identity flags while holding the SDK state lock."""

    try:
        with client._state_lock:
            return (
                client._loggedin,
                client._active_md_identity,
                client._diagnostic_identity_unverified,
                client._diagnostic_identity_unverified_active,
                client._diagnostic_identity_unverified_trading_day,
            )
    except Exception:
        return None


def _valid_verified_login(
    client: Any,
    login_field: Any,
    *,
    front: str,
    broker_id: str,
    user_id: str,
    initial_generation: int,
) -> tuple[int, str] | None:
    diagnostic = _diagnostic(client)
    snapshot = _md_client_snapshot(client)
    identity_state = _identity_snapshot(client)
    try:
        response_broker = login_field.BrokerID
        response_user = login_field.UserID
        trading_day = login_field.TradingDay
    except Exception:
        return None
    if (
        diagnostic is None
        or diagnostic[:4] != (1, "accepted", "zero", "zero")
        or diagnostic[4:] != _VERIFIED_SHAPES
        or type(response_broker) is not str
        or response_broker != broker_id
        or type(response_user) is not str
        or response_user != user_id
        or not _valid_day(trading_day)
        or snapshot is None
        or snapshot[0] != front
        or snapshot[1] != broker_id
        or snapshot[2] != user_id
        or snapshot[3] <= initial_generation
        or snapshot[4] is not True
        or snapshot[5] is not True
        or identity_state is None
        or identity_state[0] is not True
        or identity_state[2] is not False
        or identity_state[3] is not False
    ):
        return None
    identity = identity_state[1]
    try:
        identity_matches = (
            type(identity.front) is str
            and identity.front == front
            and type(identity.broker_id) is str
            and identity.broker_id == broker_id
            and type(identity.user_id) is str
            and identity.user_id == user_id
            and type(identity.connection_generation) is int
            and identity.connection_generation == snapshot[3]
            and type(identity.request_id) is int
            and identity.request_id == 0
            and type(identity.trading_day) is str
            and identity.trading_day == trading_day
            and identity.authenticated is True
        )
    except Exception:
        return None
    if not identity_matches:
        return None
    return snapshot[3], trading_day


def _valid_identity_unverified_login(
    client: Any,
    *,
    front: str,
    broker_id: str,
    user_id: str,
    initial_generation: int,
) -> tuple[int, str] | None:
    diagnostic = _diagnostic(client)
    snapshot = _md_client_snapshot(client)
    identity_state = _identity_snapshot(client)
    if (
        diagnostic is None
        or diagnostic[:4] != (1, "identity_unverified", "zero", "zero")
        or diagnostic[4:] != _UNVERIFIED_SHAPES
        or snapshot is None
        or snapshot[0] != front
        or snapshot[1] != broker_id
        or snapshot[2] != user_id
        or snapshot[3] <= initial_generation
        or snapshot[4] is not True
        or snapshot[5] is not False
        or identity_state is None
        or identity_state[0] is not False
        or identity_state[1] is not None
        or identity_state[2] is not True
        or identity_state[3] is not True
        or not _valid_day(identity_state[4])
    ):
        return None
    return snapshot[3], identity_state[4]


def _terminal_flags(client: Any, *, login_state: str) -> bool:
    expected_unverified = login_state == "identity_unverified"
    diagnostic = _diagnostic(client)
    expected_disposition = "identity_unverified" if expected_unverified else "terminal"
    if (
        diagnostic is None
        or diagnostic[:4] != (1, expected_disposition, "zero", "zero")
        or diagnostic[4:] != (_UNVERIFIED_SHAPES if expected_unverified else _VERIFIED_SHAPES)
    ):
        return False
    try:
        with client._state_lock:
            return (
                client.diagnostic_terminal is True
                and client.diagnostic_terminal_reason == "diagnostic_complete"
                and client.diagnostic_subscription_acknowledged is True
                and client.diagnostic_first_tick_received is True
                and client._diagnostic_identity_unverified is expected_unverified
                and client._diagnostic_identity_unverified_active is False
                and client._loggedin is False
                and client._active_md_identity is None
            )
    except Exception:
        return False


def _progress_evidence(
    state: dict[str, Any], condition: threading.Condition
) -> CtpI10OneShotMdProgressEvidence:
    """Copy only confirmed I10 progress into a value-redacted receipt."""

    with condition:
        login_state = state.get("login_state")
        if login_state not in {"verified", "identity_unverified"}:
            login_state = None
        return CtpI10OneShotMdProgressEvidence(
            login_identity_state=login_state,
            subscription_acknowledged=True if state.get("acknowledged") is True else None,
            matching_tick_observed=True if state.get("tick") is True else None,
            same_trading_day_observed=True if state.get("same_trading_day") is True else None,
        )


def _reject_with_progress(
    reason: str,
    *,
    progress: CtpI10OneShotMdProgressEvidence,
    close_state: str = "not_started",
    primary_reason: str | None = None,
    client_stop_returned: bool | None = None,
) -> None:
    try:
        _reject(
            reason,
            close_state=close_state,
            primary_reason=primary_reason,
            client_stop_returned=client_stop_returned,
        )
    except CtpSdkMarketReadOnlyError as error:
        error.i10_progress_evidence = progress
        raise


def probe_i10_oneshot_md_readonly(
    *,
    admission: Any,
    credential_source: CtpMarketCredentialSource,
    client_type: Any,
    stop_receipt_type: Any,
    timeout_seconds: float = 15.0,
) -> CtpI10OneShotMdObservation:
    """Observe one login identity outcome, exact ACK, matching tick, and close.

    ``timeout_seconds`` is a cooperative observation deadline. Python cannot
    interrupt synchronous SDK ``start``, ``subscribe``, or ``stop_and_wait``
    calls, so a caller that needs a hard total wall-clock limit must run this
    adapter under a supervisor that enforces it. A late but complete close is
    rejected as ``probe_deadline_expired``; an uncertain close remains a
    stop failure and retains its account lease.
    """

    try:
        admitted = _validated_admission(admission)
        _require_i10_sdk_types(client_type, stop_receipt_type)
        timeout = _timeout(timeout_seconds)
    except CtpSdkMarketReadOnlyError as error:
        error.i10_progress_evidence = CtpI10OneShotMdProgressEvidence()
        raise
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
    primary_error: str | None = None
    connection_generation: int | None = None
    login_state: str | None = None
    same_trading_day_observed = False
    condition = threading.Condition()
    state: dict[str, Any] = {
        "acknowledged": False,
        "closed": False,
        "error": None,
        "login_callback_count": 0,
        "login_generation": None,
        "login_state": None,
        "trading_day": None,
        "subscription_submitted": False,
        "tick": False,
        "same_trading_day": False,
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

        def record_login(mode: str, callback_value: Any = None) -> None:
            with condition:
                state["login_callback_count"] += 1
                callback_count = state["login_callback_count"]
            if callback_count != 1:
                record_error("market_login_identity_mismatch")
                return
            if mode == "verified":
                identity = _valid_verified_login(
                    client,
                    callback_value,
                    front=front,
                    broker_id=broker_id,
                    user_id=user_id,
                    initial_generation=initial_generation,
                )
            else:
                identity = _valid_identity_unverified_login(
                    client,
                    front=front,
                    broker_id=broker_id,
                    user_id=user_id,
                    initial_generation=initial_generation,
                )
            if identity is None:
                record_error("market_login_identity_mismatch")
                return
            generation, trading_day = identity
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                state["login_generation"] = generation
                state["login_state"] = mode
                state["trading_day"] = trading_day
                condition.notify_all()

        def on_login(login_field: Any) -> None:
            record_login("verified", login_field)

        def on_identity_unverified() -> None:
            record_login("identity_unverified")

        def on_error(_response: Any) -> None:
            with condition:
                reason = (
                    "market_login_identity_mismatch"
                    if state["login_state"] is None
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
                mode = state["login_state"]
                was_submitted = state["subscription_submitted"]
                already_acknowledged = state["acknowledged"]
            snapshot = _md_client_snapshot(client)
            identity_state = _identity_snapshot(client)
            diagnostic = _diagnostic(client)
            try:
                error_id = response.ErrorID
            except Exception:
                error_id = None
            expected_disposition = "accepted" if mode == "verified" else "identity_unverified"
            if (
                not was_submitted
                or mode not in {"verified", "identity_unverified"}
                or generation is None
                or already_acknowledged
                or _field_text(specific_instrument, "InstrumentID") != instrument
                or type(error_id) is not int
                or error_id != 0
                or snapshot is None
                or snapshot[:4] != (front, broker_id, user_id, generation)
                or snapshot[4] is not True
                or snapshot[5] is not (mode == "verified")
                or identity_state is None
                or identity_state[0] is not (mode == "verified")
                or identity_state[2] is not (mode == "identity_unverified")
                or identity_state[3] is not (mode == "identity_unverified")
                or diagnostic is None
                or diagnostic[:4] != (1, expected_disposition, "zero", "zero")
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
                mode = state["login_state"]
                trading_day = state["trading_day"]
                acknowledged = state["acknowledged"]
                already_observed = state["tick"]
            snapshot = _md_client_snapshot(client)
            if (
                not acknowledged
                or mode not in {"verified", "identity_unverified"}
                or generation is None
                or already_observed
                or snapshot is None
                or snapshot[:4] != (front, broker_id, user_id, generation)
                or snapshot[4] is not False
                or snapshot[5] is not False
                or not _terminal_flags(client, login_state=mode)
                or trading_day is None
                or _field_text(tick, "TradingDay") != trading_day
                or not _valid_tick(tick, instrument, exchange)
            ):
                record_error("market_probe_failed")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["tick"] = True
                    state["same_trading_day"] = True
                    condition.notify_all()

        client.on_login = on_login
        client.on_identity_unverified = on_identity_unverified
        client.on_error = on_error
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_tick = on_tick
        client.start(block=False)
        if time.monotonic() >= deadline:
            _reject("probe_deadline_expired")

        with condition:
            while state["login_state"] is None:
                if state["error"] is not None:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _reject("market_login_timeout")
                condition.wait(remaining)
            if state["error"] is not None or state["login_callback_count"] != 1:
                _reject(state["error"] or "market_login_identity_mismatch")
            generation = state["login_generation"]
            if type(generation) is not int:
                _reject("market_login_identity_mismatch")
            if time.monotonic() >= deadline:
                _reject("probe_deadline_expired")
            state["subscription_submitted"] = True

        request_result = client.subscribe([instrument])
        if type(request_result) is not int or request_result != 0:
            _reject("market_subscription_rejected")
        if time.monotonic() >= deadline:
            _reject("probe_deadline_expired")

        with condition:
            while not (state["acknowledged"] and state["tick"]):
                if state["error"] is not None:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _reject(
                        "subscription_ack_timeout"
                        if not state["acknowledged"]
                        else "matching_tick_not_observed"
                    )
                condition.wait(remaining)
            if state["error"] is not None:
                _reject(state["error"])
            if time.monotonic() >= deadline:
                _reject("probe_deadline_expired")
            state["closed"] = True
            connection_generation = state["login_generation"]
            login_state = state["login_state"]
            same_trading_day_observed = state.get("same_trading_day") is True
    except CtpSdkMarketReadOnlyError as error:
        primary_error = error.reason
    except Exception:
        # SDK exceptions may contain provider values; retain only a fixed label.
        primary_error = "market_probe_failed"
    finally:
        if client is None:
            lease.release()
        else:
            with condition:
                state["closed"] = True
            close_state, client_stop_returned, close_complete = _close_client(
                client,
                lease=lease,
                stop_receipt_type=stop_receipt_type,
            )

    if not close_complete:
        _reject_with_progress(
            "market_client_stop_failed",
            progress=_progress_evidence(state, condition),
            close_state=close_state,
            primary_reason=primary_error,
            client_stop_returned=client_stop_returned,
        )
    if time.monotonic() >= deadline:
        _reject_with_progress(
            "probe_deadline_expired",
            progress=_progress_evidence(state, condition),
            close_state=close_state,
            client_stop_returned=client_stop_returned,
        )
    if primary_error is not None:
        _reject_with_progress(
            primary_error,
            progress=_progress_evidence(state, condition),
            close_state=close_state,
            client_stop_returned=client_stop_returned,
        )
    if (
        type(connection_generation) is not int
        or login_state not in {"verified", "identity_unverified"}
        or not same_trading_day_observed
    ):
        _reject_with_progress(
            "market_observation_incomplete",
            progress=_progress_evidence(state, condition),
            close_state=close_state,
            client_stop_returned=client_stop_returned,
        )
    return CtpI10OneShotMdObservation(
        md_front_sha256=hashlib.sha256(front.encode("utf-8")).hexdigest(),
        account_fingerprint_sha256=admitted.account_fingerprint_sha256,
        instrument_id=instrument,
        exchange_id=exchange,
        connection_generation=connection_generation,
        login_identity_state=login_state,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
        client_stop_returned=client_stop_returned is True,
        native_join_pending=False,
    )


__all__ = [
    "CtpI10OneShotMdObservation",
    "CtpI10OneShotMdProgressEvidence",
    "probe_i10_oneshot_md_readonly",
]
