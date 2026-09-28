"""Unregistered I3 one-shot, market-data-only diagnostic adapter.

The I3 SDK's ``OneShotMdDiagnosticClient`` sends one login request with ID 0
and accepts its single subscription only after a successful login callback.
This adapter preserves that callback-driven order and requires a matching
single tick plus a complete native stop receipt. It has no registry entry,
CLI route, Trader client, or execution capability. Callers must perform the
sealed runtime, artifact, and credential gates before injecting the client
and receipt types.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .ctp_sdk_market_readonly import (
    _MAX_NATIVE_JOIN_WAIT_SECONDS,
    _AccountLease,
    _MD_LOGIN_BROKER_ID_SHAPES,
    _MD_LOGIN_NATIVE_FIELD_SHAPES,
    _MD_LOGIN_TRADING_DAY_SHAPES,
    _MD_LOGIN_USER_ID_SHAPES,
    _account_lock_key,
    _field_text,
    _hold_lease_unknown,
    _md_client_snapshot,
    _read_credential,
    _reject,
    _timeout,
    _valid_tick,
    _validated_admission,
    CtpMarketCredentialSource,
    CtpSdkMarketReadOnlyError,
)


_I3_SDK_MODULE = "bt_api_ctp.ctp.client"
_I3_CLIENT_NAME = "OneShotMdDiagnosticClient"
_I3_STOP_RECEIPT_NAME = "CtpNativeStopReceipt"
_LOGIN_DIAGNOSTIC_ACCEPTED = (1, "accepted", "zero", "zero")
_LOGIN_DIAGNOSTIC_TERMINAL = (1, "terminal", "zero", "zero")
_LOGIN_CALLBACK_DISPOSITIONS = frozenset(
    {
        "none",
        "stale_spi",
        "generation_mismatch",
        "request_id_type_invalid",
        "request_id_mismatch",
        "nonterminal",
        "accepted",
        "provider_rejected",
        "identity_rejected",
        "terminal",
    }
)
_LOGIN_REQUEST_ID_RELATIONS = frozenset(
    {"not_observed", "invalid", "zero", "lower", "equal", "higher"}
)
_LOGIN_RESPONSE_ERROR_STATUSES = frozenset(
    {"not_observed", "missing", "invalid", "zero", "nonzero"}
)
_LOGIN_FAILURE_CATEGORY_BY_TERMINAL_REASON = {
    "login_request_id_type_invalid": "request_id_invalid",
    "login_request_id_mismatch": "request_id_mismatch",
    "login_response_nonterminal": "response_nonterminal",
    "provider_login_rejected": "provider_rejected",
    "login_response_invalid": "response_invalid",
    "broker_id_mismatch": "broker_id_mismatch",
    "user_id_mismatch": "user_id_mismatch",
    "trading_day_invalid": "trading_day_invalid",
}


@dataclass(frozen=True)
class CtpI3OneShotMdObservation:
    """A closed, exact-scope observation from one I3 one-shot MD client."""

    md_front_sha256: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    connection_generation: int
    login_request_id: int
    market_login_ready: bool
    subscription_acknowledged: bool
    matching_tick_observed: bool
    client_stop_returned: bool
    native_join_pending: bool

    @property
    def probe_session_closed(self) -> bool:
        """Whether the SDK returned a complete stop receipt."""

        return self.client_stop_returned and not self.native_join_pending

    @property
    def order_submission_authorized(self) -> bool:
        """This observation never authorizes trading."""

        return False

    @property
    def trading_writes(self) -> int:
        """The market-data adapter has no trading request path."""

        return 0

    @property
    def settlement_writes(self) -> int:
        """The market-data adapter has no settlement request path."""

        return 0

    def as_public_dict(self) -> dict[str, Any]:
        """Return a value-free summary without raw account or front values."""

        return {
            "account_scope_bound": bool(self.account_fingerprint_sha256),
            "client_stop_returned": self.client_stop_returned,
            "connection_generation": self.connection_generation,
            "exchange_id": self.exchange_id,
            "instrument_id": self.instrument_id,
            "login_request_id": self.login_request_id,
            "market_login_ready": self.market_login_ready,
            "matching_tick_observed": self.matching_tick_observed,
            "md_front_sha256": self.md_front_sha256,
            "native_join_pending": self.native_join_pending,
            "order_submission_authorized": False,
            "probe_session_closed": self.probe_session_closed,
            "settlement_writes": 0,
            "subscription_acknowledged": self.subscription_acknowledged,
            "trading_writes": 0,
        }


def _require_i3_sdk_types(client_type: Any, stop_receipt_type: Any) -> None:
    """Check class surface labels; composition must inject installed SDK classes."""

    if (
        type(client_type) is not type
        or client_type.__name__ != _I3_CLIENT_NAME
        or client_type.__module__ != _I3_SDK_MODULE
        or type(stop_receipt_type) is not type
        or stop_receipt_type.__name__ != _I3_STOP_RECEIPT_NAME
        or stop_receipt_type.__module__ != _I3_SDK_MODULE
    ):
        _reject("market_client_type_required")


def _login_diagnostic(client: Any) -> tuple[Any, ...] | None:
    """Copy the SDK's fixed login callback classification, without payloads."""

    try:
        diagnostic = client.login_callback_diagnostic
        count = diagnostic.callback_count
        disposition = diagnostic.disposition.value
        request_relation = diagnostic.request_id_relation.value
        response_status = diagnostic.response_error_status.value
    except Exception:
        return None
    if (
        type(count) is not int
        or not 0 <= count <= 1_000_000
        or type(disposition) is not str
        or disposition not in _LOGIN_CALLBACK_DISPOSITIONS
        or type(request_relation) is not str
        or request_relation not in _LOGIN_REQUEST_ID_RELATIONS
        or type(response_status) is not str
        or response_status not in _LOGIN_RESPONSE_ERROR_STATUSES
    ):
        return None
    return count, disposition, request_relation, response_status


def _login_broker_id_shape(client: Any) -> str | None:
    """Copy the I5 SDK's closed broker-ID shape enum, when available.

    This is value-only diagnostic evidence. The raw broker ID and every
    unknown SDK value are omitted. Earlier SDKs do not expose this field.
    """

    try:
        value = client.login_callback_diagnostic.broker_id_shape.value
    except Exception:
        return None
    if type(value) is str and value in _MD_LOGIN_BROKER_ID_SHAPES:
        return value
    return None


def _login_user_id_shape(client: Any) -> str | None:
    """Copy the I6 SDK's closed user-ID shape enum, when available."""

    try:
        value = client.login_callback_diagnostic.user_id_shape.value
    except Exception:
        return None
    if type(value) is str and value in _MD_LOGIN_USER_ID_SHAPES:
        return value
    return None


def _login_trading_day_shape(client: Any) -> str | None:
    """Copy the I6 SDK's closed trading-day shape enum, when available."""

    try:
        value = client.login_callback_diagnostic.trading_day_shape.value
    except Exception:
        return None
    if type(value) is str and value in _MD_LOGIN_TRADING_DAY_SHAPES:
        return value
    return None


def _login_native_field_shape(client: Any, field_name: str) -> str | None:
    """Copy one of the SDK's bounded native login-field shape enums."""

    if field_name not in {"native_broker_id_shape", "native_user_id_shape"}:
        return None
    try:
        value = getattr(client.login_callback_diagnostic, field_name).value
    except Exception:
        return None
    if type(value) is str and value in _MD_LOGIN_NATIVE_FIELD_SHAPES:
        return value
    return None


def _failure_diagnostics(client: Any) -> dict[str, Any]:
    """Copy only bounded callback enums and a fixed login-failure category."""

    diagnostic = _login_diagnostic(client)
    if diagnostic is None:
        callback_count = disposition = request_relation = response_status = None
    else:
        callback_count, disposition, request_relation, response_status = diagnostic

    category = None
    try:
        terminal_reason = client.diagnostic_terminal_reason
    except Exception:
        terminal_reason = None
    if type(terminal_reason) is str:
        category = _LOGIN_FAILURE_CATEGORY_BY_TERMINAL_REASON.get(terminal_reason)

    return {
        "login_callback_count": callback_count,
        "login_callback_disposition": disposition,
        "login_request_id_relation": request_relation,
        "login_response_error_status": response_status,
        "login_failure_category": category,
        "login_broker_id_shape": _login_broker_id_shape(client),
        "login_user_id_shape": _login_user_id_shape(client),
        "login_trading_day_shape": _login_trading_day_shape(client),
        "native_broker_id_shape": _login_native_field_shape(
            client, "native_broker_id_shape"
        ),
        "native_user_id_shape": _login_native_field_shape(client, "native_user_id_shape"),
    }


def _binding_error(
    snapshot: tuple[Any, ...] | None,
    *,
    front: str,
    broker_id: str,
    user_id: str,
    expected_generation: int | None,
    require_ready: bool,
    require_terminal: bool = False,
) -> str | None:
    """Check stable client identity while allowing the I3 tick terminal state."""

    if snapshot is None:
        return "market_session_state_unavailable"
    current_front, current_broker, current_user, generation, connected, logged_in = snapshot
    if current_front != front:
        return "market_front_binding_mismatch"
    if current_broker != broker_id or current_user != user_id:
        return "market_client_identity_mismatch"
    if generation < 1:
        return "market_session_not_ready"
    if expected_generation is not None and generation != expected_generation:
        return "market_connection_generation_changed"
    if require_ready and (connected is not True or logged_in is not True):
        return "market_session_not_ready"
    if require_terminal and (connected is not False or logged_in is not False):
        return "market_session_state_unavailable"
    return None


def _diagnostic_flags(client: Any) -> tuple[Any, ...] | None:
    """Read I3's fixed one-shot terminal and subscription flags."""

    try:
        return (
            client.diagnostic_terminal,
            client.diagnostic_terminal_reason,
            client.diagnostic_subscription_acknowledged,
            client.diagnostic_first_tick_received,
        )
    except Exception:
        return None


def _accepted_login_callback(client: Any, *, terminal: bool = False) -> bool:
    diagnostic = _login_diagnostic(client)
    expected = _LOGIN_DIAGNOSTIC_TERMINAL if terminal else _LOGIN_DIAGNOSTIC_ACCEPTED
    return diagnostic == expected


def _validated_i3_stop_receipt(
    receipt: Any,
    *,
    receipt_type: type[Any],
    expected_generation: int | None,
) -> tuple[bool, bool | None, bool | None] | None:
    """Validate the exact I3 public receipt and its internally coherent fields."""

    if type(receipt) is not receipt_type or type(expected_generation) is not int:
        return None
    try:
        generation = receipt.connection_generation
        join_required = receipt.join_required
        join_completed = receipt.join_completed
        native_released = receipt.native_released
        thread_alive = receipt.thread_alive
        timed_out = receipt.timed_out
        client_stop_returned = receipt.client_stop_returned
        complete = receipt.complete
    except Exception:
        return None
    if (
        type(generation) is not int
        or generation < 0
        or generation != expected_generation
        or type(join_required) is not bool
        or type(join_completed) is not bool
        or type(native_released) is not bool
        or (thread_alive is not None and type(thread_alive) is not bool)
        or type(timed_out) is not bool
        or (client_stop_returned is not None and type(client_stop_returned) is not bool)
        or type(complete) is not bool
        or (join_completed and thread_alive is not False)
    ):
        return None
    derived_complete = (
        native_released
        and (not join_required or join_completed)
        and thread_alive is False
        and not timed_out
        and client_stop_returned is True
    )
    if complete is not derived_complete:
        return None
    return complete, thread_alive, client_stop_returned


def _close_client(
    client: Any,
    *,
    lease: _AccountLease,
    stop_receipt_type: type[Any],
) -> tuple[str, bool | None, bool]:
    """Require a coherent stop receipt; retain the account lease if uncertain."""

    try:
        join_thread = getattr(client, "_thread", None)
    except Exception:
        join_thread = None
    before_stop = _md_client_snapshot(client)
    expected_generation = None if before_stop is None else before_stop[3]
    try:
        stop_and_wait = getattr(client, "stop_and_wait")
    except Exception:
        stop_and_wait = None
    if not callable(stop_and_wait):
        stop_returned: bool | None = None
        try:
            stop = getattr(client, "stop", None)
            if callable(stop):
                stop()
                stop_returned = True
        except Exception:
            stop_returned = False
        _hold_lease_unknown(lease, client, join_thread)
        return "native_stop_method_unknown", stop_returned, False

    try:
        receipt = stop_and_wait(timeout=_MAX_NATIVE_JOIN_WAIT_SECONDS)
    except Exception:
        _hold_lease_unknown(lease, client, join_thread)
        return "stop_failed", None, False

    stop_state = _validated_i3_stop_receipt(
        receipt,
        receipt_type=stop_receipt_type,
        expected_generation=expected_generation,
    )
    if stop_state is None:
        _hold_lease_unknown(lease, client, join_thread)
        return "native_stop_receipt_unknown", None, False

    # A complete native stop receipt is not sufficient while an SDK SPI
    # callback still owns the client's callback context. This exact public
    # count is required for acceptance: artifacts that lack it, including the
    # earlier I3 wheel, fail closed; I4 exposes the count required here.
    try:
        active_callbacks = getattr(client, "diagnostic_callbacks_active")
    except Exception:
        active_callbacks = None
    if type(active_callbacks) is not int or active_callbacks < 0 or active_callbacks != 0:
        _hold_lease_unknown(lease, client, join_thread)
        return "native_stop_receipt_unknown", stop_state[2], False

    complete, receipt_thread_alive, client_stop_returned = stop_state
    if complete:
        lease.release()
        return "stop_returned", True, True

    if receipt_thread_alive is True:
        if type(join_thread) is threading.Thread:
            try:
                thread_alive = join_thread.is_alive()
            except Exception:
                thread_alive = None
        else:
            thread_alive = None
        if thread_alive is True:
            _hold_lease_unknown(lease, client, join_thread)
            return "native_join_pending", client_stop_returned, False
        if thread_alive is False:
            _hold_lease_unknown(lease, client, join_thread)
            return "native_stop_receipt_inconsistent", client_stop_returned, False
        _hold_lease_unknown(lease, client, join_thread)
        return "native_join_state_unknown", client_stop_returned, False

    _hold_lease_unknown(lease, client, join_thread)
    return "native_stop_incomplete", client_stop_returned, False


def probe_i3_oneshot_md_readonly(
    *,
    admission: Any,
    credential_source: CtpMarketCredentialSource,
    client_type: Any,
    stop_receipt_type: Any,
    timeout_seconds: float = 15.0,
) -> CtpI3OneShotMdObservation:
    """Run one login-ID-0, exact-subscription, one-tick I3 MD observation.

    The admission must already be the exact sealed read-only route and the
    credential source must revalidate its seal for every value read. This
    helper preserves the admission's front and contract strings verbatim. It
    calls ``subscribe`` only after the accepted login callback and never
    creates a Trader or execution client. The injected types are intended for
    the reviewed I3 composition and offline fakes; this module is not
    registered or exposed through the default CLI.
    """

    admitted = _validated_admission(admission)
    _require_i3_sdk_types(client_type, stop_receipt_type)
    timeout = _timeout(timeout_seconds)
    front = admitted.md_front
    instrument = admitted.instrument_id
    exchange = admitted.exchange_id
    deadline = time.monotonic() + timeout
    lease = _AccountLease(_account_lock_key(admitted.account_fingerprint_sha256))
    lease.acquire()

    client = None
    client_stop_returned: bool | None = None
    close_state = "not_started"
    close_complete = False
    primary_error: str | None = None
    connection_generation: int | None = None
    failure_diagnostics: dict[str, Any] = {
        "login_callback_count": None,
        "login_callback_disposition": None,
        "login_request_id_relation": None,
        "login_response_error_status": None,
        "login_failure_category": None,
        "login_broker_id_shape": None,
        "login_user_id_shape": None,
        "login_trading_day_shape": None,
    }
    condition = threading.Condition()
    state: dict[str, Any] = {
        "acknowledged": False,
        "closed": False,
        "error": None,
        "login": False,
        "login_callback_count": 0,
        "login_generation": None,
        "subscription_submitted": False,
        "tick": False,
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

        client = client_type(front, broker_id, user_id, password)
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

        def check_binding(
            *, expected_generation: int | None, require_ready: bool, require_terminal: bool = False
        ) -> tuple[Any, ...] | None:
            snapshot = _md_client_snapshot(client)
            reason = _binding_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
                expected_generation=expected_generation,
                require_ready=require_ready,
                require_terminal=require_terminal,
            )
            if reason is not None:
                record_error(reason)
                return None
            return snapshot

        def on_login(login_field: Any) -> None:
            with condition:
                state["login_callback_count"] += 1
                callback_count = state["login_callback_count"]
            if callback_count != 1 or not _accepted_login_callback(client):
                record_error("market_login_identity_mismatch")
                return
            try:
                login_broker = getattr(login_field, "BrokerID")
                login_user = getattr(login_field, "UserID")
            except Exception:
                record_error("market_login_identity_unavailable")
                return
            if (
                type(login_broker) is not str
                or type(login_user) is not str
                or login_broker != broker_id
                or login_user != user_id
            ):
                record_error("market_login_identity_mismatch")
                return
            snapshot = check_binding(
                expected_generation=None,
                require_ready=True,
            )
            if snapshot is None or snapshot[3] <= initial_generation:
                record_error("market_session_not_ready")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["login"] = True
                    state["login_generation"] = snapshot[3]
                    condition.notify_all()

        def on_error(_response: Any) -> None:
            with condition:
                reason = (
                    "market_login_identity_mismatch"
                    if not state["login"]
                    else "market_subscription_rejected"
                    if not state["acknowledged"]
                    else "market_probe_failed"
                )
            record_error(reason)

        def on_disconnect(_reason: Any) -> None:
            record_error("market_front_disconnected")

        def on_subscribe(specific_instrument: Any, response: Any) -> None:
            with condition:
                login_generation = state["login_generation"]
                was_submitted = state["subscription_submitted"]
                already_acknowledged = state["acknowledged"]
            if not was_submitted or login_generation is None or already_acknowledged:
                record_error("market_subscription_rejected")
                return
            if _field_text(specific_instrument, "InstrumentID") != instrument:
                record_error("market_subscription_rejected")
                return
            try:
                error_id = getattr(response, "ErrorID")
            except Exception:
                error_id = None
            flags = _diagnostic_flags(client)
            snapshot = check_binding(
                expected_generation=login_generation,
                require_ready=True,
            )
            if (
                type(error_id) is not int
                or error_id != 0
                or flags is None
                or flags[2] is not True
                or snapshot is None
            ):
                record_error("market_subscription_rejected")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["acknowledged"] = True
                    condition.notify_all()

        def on_tick(tick: Any) -> None:
            with condition:
                login_generation = state["login_generation"]
                acknowledged = state["acknowledged"]
                already_observed = state["tick"]
            if not acknowledged or login_generation is None or already_observed:
                record_error("market_probe_failed")
                return
            snapshot = check_binding(
                expected_generation=login_generation,
                require_ready=False,
                require_terminal=True,
            )
            flags = _diagnostic_flags(client)
            if (
                snapshot is None
                or flags is None
                or flags[0] is not True
                or flags[1] != "diagnostic_complete"
                or flags[2] is not True
                or flags[3] is not True
                or not _accepted_login_callback(client, terminal=True)
                or not _valid_tick(tick, instrument, exchange)
            ):
                record_error("market_probe_failed")
                return
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["tick"] = True
                    condition.notify_all()

        client.on_login = on_login
        client.on_error = on_error
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_tick = on_tick

        client.start(block=False)
        if time.monotonic() >= deadline:
            _reject("probe_deadline_expired")
        with condition:
            while not state["login"]:
                if state["error"] is not None:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _reject("market_login_timeout")
                condition.wait(remaining)

        login_generation = state["login_generation"]
        if (
            type(login_generation) is not int
            or not _accepted_login_callback(client)
            or state["login_callback_count"] != 1
        ):
            _reject("market_login_identity_mismatch")
        snapshot = _md_client_snapshot(client)
        binding_reason = _binding_error(
            snapshot,
            front=front,
            broker_id=broker_id,
            user_id=user_id,
            expected_generation=login_generation,
            require_ready=True,
        )
        if binding_reason is not None:
            _reject(binding_reason)

        with condition:
            if state["error"] is not None:
                _reject(state["error"])
            state["subscription_submitted"] = True
        request_result = client.subscribe([instrument])
        if type(request_result) is not int or request_result != 0:
            _reject("market_subscription_rejected")

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
            state["closed"] = True
            connection_generation = login_generation
    except CtpSdkMarketReadOnlyError as error:
        primary_error = error.reason
    except Exception:
        # Native SDK exceptions can contain provider values; expose no text.
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
            failure_diagnostics = _failure_diagnostics(client)

    if not close_complete:
        _reject(
            "market_client_stop_failed",
            close_state=close_state,
            primary_reason=primary_error,
            client_stop_returned=client_stop_returned,
            **failure_diagnostics,
        )
    if primary_error is not None:
        _reject(
            primary_error,
            close_state=close_state,
            client_stop_returned=client_stop_returned,
            **failure_diagnostics,
        )
    assert connection_generation is not None
    return CtpI3OneShotMdObservation(
        md_front_sha256=hashlib.sha256(front.encode("utf-8")).hexdigest(),
        account_fingerprint_sha256=admitted.account_fingerprint_sha256,
        instrument_id=instrument,
        exchange_id=exchange,
        connection_generation=connection_generation,
        login_request_id=0,
        market_login_ready=True,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        client_stop_returned=client_stop_returned,
        native_join_pending=False,
    )


__all__ = ["CtpI3OneShotMdObservation", "probe_i3_oneshot_md_readonly"]
