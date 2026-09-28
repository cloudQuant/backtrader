"""One-shot public-API CTP SimNow startup and native-readiness observation.

This module is intentionally unregistered.  The caller must complete its
artifact/provenance gate, resolve the credentials from the current sealed
configuration, and pass the exact selected scope before calling it.  The
adapter starts one already-constructed ``TraderClient`` and one fresh
``MdClient`` against that exact pair, then requires matching TD login, MD
login, one exact subscription acknowledgement, and one valid matching tick.

The readiness wait uses one monotonic deadline and continually checks public
session state. The SDK's public ``start(block=False)`` and the synchronous
``stop()`` inside ``stop_and_wait`` are native calls whose duration the SDK
does not bound. The timeout passed to ``stop_and_wait`` bounds only its Join
observation, not the complete call. This adapter bounds its readiness
observation phase but cannot promise a hard wall-clock bound around native
startup or cleanup; that requires a supervising process that can terminate a
stuck caller. It never retries, changes fronts, submits a trading request, or
reads private SDK attributes.
The SDK's ``TraderClient.start`` still performs its normal session
authentication and login sequence; the adapter itself does not submit an
order, cancel, or settlement-confirmation request.

On success, the caller owns both still-open clients. ``market_client_sink``
hands the MD client to that owner. A managed composition may also supply
``failure_cleanup`` so readiness failure uses the same idempotent, lease-aware
resource owner as later session shutdown. Without that hook, this adapter
stops both clients itself on failure.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .ctp_simnow_managed_operator import CtpSimNowManagedScopeSelection
from .ctp_simnow_managed_runtime import (
    CtpSimNowNativeReadiness,
    CtpSimulationExecutionError,
)
from .ctp_simulation_execution import CtpSimulationExecutionRegistration
from .ctp_native_shutdown import stop_ctp_native_client


class CtpSimNowNativeReadinessError(CtpSimulationExecutionError):
    """A redacted failure while starting or checking a SimNow native session."""

    def __init__(self, reason: str, *, close_state: str = "not_started") -> None:
        self.close_state = close_state
        super().__init__(reason)


@dataclass(frozen=True)
class _TdSnapshot:
    generation: int
    trading_day: str


@dataclass(frozen=True)
class _MdSnapshot:
    generation: int
    trading_day: str


@dataclass(frozen=True)
class CtpSimNowNativeStartupConfig:
    """Credential/config fields needed by the public MD startup adapter.

    The trader client itself is supplied already constructed by the
    artifact-first composition.  Secret fields are excluded from repr so a
    diagnostic representation cannot disclose them.
    """

    td_front: str
    md_front: str
    broker_id: str
    user_id: str
    password: str = field(repr=False)


def _reject(reason: str) -> None:
    raise CtpSimNowNativeReadinessError(reason)


def _error_id(info: Any) -> int | None:
    try:
        value = getattr(info, "ErrorID")
    except Exception:
        return None
    if type(value) is int:
        return value
    if type(value) is str and value.isascii() and value.isdigit():
        return int(value)
    return None


def _valid_day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        time.strptime(value, "%Y%m%d")
    except (OverflowError, ValueError):
        return False
    return True


def _expected_account_digest(broker_id: str, user_id: str) -> tuple[str, str]:
    short = hashlib.sha256("{0}:{1}".format(broker_id, user_id).encode("utf-8")).hexdigest()[:16]
    return short, hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


def _validate_inputs(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowNativeStartupConfig,
    md_client_factory: Callable[..., Any],
    market_client_sink: Callable[[Any], None],
    timeout_seconds: float,
) -> CtpSimulationExecutionRegistration:
    if type(selection) is not CtpSimNowManagedScopeSelection:
        _reject("managed_simnow_selection_required")
    registration = selection.execution_registration
    if type(registration) is not CtpSimulationExecutionRegistration:
        _reject("managed_simnow_registration_required")
    if type(config) is not CtpSimNowNativeStartupConfig:
        _reject("managed_simnow_startup_config_required")
    if not callable(md_client_factory) or not callable(market_client_sink):
        _reject("managed_simnow_md_factory_and_sink_required")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 120
    ):
        _reject("managed_simnow_timeout_invalid")
    if (
        config.td_front != registration.td_front
        or config.md_front != registration.md_front
        or config.broker_id == ""
        or config.user_id == ""
        or config.password == ""
        or any(
            type(value) is not str or value != value.strip()
            for value in (
                config.td_front,
                config.md_front,
                config.broker_id,
                config.user_id,
                config.password,
            )
        )
    ):
        _reject("managed_simnow_startup_config_scope_mismatch")
    if (
        registration.environment != "simnow"
        or registration.sdk_profile != "config_front_pair"
        or registration.config_digest != selection.config_digest
        or registration.md_front != selection.front_pair_selection.pair.md_front
        or registration.td_front != selection.front_pair_selection.pair.td_front
    ):
        _reject("managed_simnow_selection_scope_mismatch")
    _, account_digest = _expected_account_digest(config.broker_id, config.user_id)
    if not hmac.compare_digest(account_digest, registration.account_fingerprint_sha256):
        _reject("managed_simnow_startup_account_mismatch")
    required_methods = (
        "start",
        "stop",
        "get_session_state",
        "get_front_binding_state",
        "get_query_session_scope",
    )
    if any(not callable(getattr(trader_client, name, None)) for name in required_methods):
        _reject("managed_simnow_td_public_api_unavailable")
    try:
        state = trader_client.get_session_state()
        front_state = trader_client.get_front_binding_state()
    except Exception:
        _reject("managed_simnow_td_initial_state_unavailable")
    if (
        type(state) is not dict
        or type(front_state) is not dict
        or state.get("connection_generation") != 0
        or state.get("connected") is not False
        or state.get("read_only_ready") is not False
        or front_state.get("configured_front") != registration.td_front
        or front_state.get("connected") is not False
        or front_state.get("native_api_current") is not False
    ):
        _reject("managed_simnow_td_client_not_fresh_or_scope_mismatch")
    return registration


def _td_snapshot(
    client: Any,
    config: CtpSimNowNativeStartupConfig,
    registration: CtpSimulationExecutionRegistration,
) -> _TdSnapshot | None:
    """Read and validate authenticated TD identity through public methods."""

    try:
        state = client.get_session_state()
        front_state = client.get_front_binding_state()
        scope = client.get_query_session_scope()
    except Exception:
        _reject("managed_simnow_td_state_unavailable")
    if type(state) is not dict or type(front_state) is not dict:
        _reject("managed_simnow_td_state_unavailable")
    if getattr(scope, "read_only_ready", None) is not True:
        generation = state.get("connection_generation")
        if type(generation) is int and generation > 1:
            _reject("managed_simnow_td_generation_changed")
        if state.get("last_error"):
            _reject("managed_simnow_td_login_failed")
        return None
    generation = getattr(scope, "connection_generation", None)
    day = getattr(scope, "trading_day", None)
    short_account, account_digest = _expected_account_digest(config.broker_id, config.user_id)
    if (
        getattr(scope, "broker_id", None) != config.broker_id
        or getattr(scope, "investor_id", None) != config.user_id
        or getattr(scope, "account_fingerprint", None) != short_account
        or state.get("account_fingerprint") != short_account
        or state.get("read_only_ready") is not True
        or state.get("trading_ready") is not False
        or state.get("auto_settlement_confirm") is not False
        or type(generation) is not int
        or generation != 1
        or state.get("connection_generation") != generation
        or not _valid_day(day)
        or state.get("trading_day") != day
        or account_digest != registration.account_fingerprint_sha256
        or front_state.get("configured_front") != registration.td_front
        or front_state.get("registered_front") != registration.td_front
        or front_state.get("connection_confirmed_front") != registration.td_front
        or front_state.get("connected") is not True
        or front_state.get("native_api_current") is not True
        or front_state.get("bound_identity_current") is not True
        or front_state.get("connection_generation") != generation
    ):
        _reject("managed_simnow_td_identity_or_generation_mismatch")
    return _TdSnapshot(generation=generation, trading_day=day)


def _md_snapshot(
    client: Any,
    config: CtpSimNowNativeStartupConfig,
    registration: CtpSimulationExecutionRegistration,
) -> _MdSnapshot | None:
    """Read the current authenticated MD identity through public properties."""

    try:
        if (
            getattr(client, "front", None) != registration.md_front
            or getattr(client, "broker_id", None) != config.broker_id
            or getattr(client, "user_id", None) != config.user_id
        ):
            _reject("managed_simnow_md_front_or_account_mismatch")
        generation = getattr(client, "connection_generation")
        ready = getattr(client, "is_ready")
        identity = getattr(client, "active_md_identity")
    except CtpSimNowNativeReadinessError:
        raise
    except Exception:
        _reject("managed_simnow_md_state_unavailable")
    if identity is None or ready is not True:
        if type(generation) is int and generation > 1:
            _reject("managed_simnow_md_generation_changed")
        return None
    identity_generation = getattr(identity, "connection_generation", None)
    day = getattr(identity, "trading_day", None)
    if (
        getattr(identity, "front", None) != registration.md_front
        or getattr(identity, "broker_id", None) != config.broker_id
        or getattr(identity, "user_id", None) != config.user_id
        or getattr(identity, "authenticated", None) is not True
        or type(generation) is not int
        or generation != 1
        or identity_generation != generation
        or not _valid_day(day)
    ):
        _reject("managed_simnow_md_identity_or_generation_mismatch")
    return _MdSnapshot(generation=generation, trading_day=day)


def _matching_tick(tick: Any, registration: CtpSimulationExecutionRegistration) -> bool:
    try:
        instrument = getattr(tick, "InstrumentID")
        exchange = getattr(tick, "ExchangeID")
        last_price = float(getattr(tick, "LastPrice"))
        volume = getattr(tick, "Volume")
    except Exception:
        return False
    return bool(
        type(instrument) is str
        and instrument == registration.instrument_id
        and type(exchange) is str
        and exchange == registration.exchange_id
        and math.isfinite(last_price)
        and last_price > 0
        and type(volume) is int
        and volume >= 0
    )


def _close_both(trader_client: Any, md_client: Any) -> bool:
    failed = False
    # MD closes before TD, and both are attempted even if one receipt fails.
    for client in (md_client, trader_client):
        if client is None:
            continue
        if not stop_ctp_native_client(client):
            failed = True
    return not failed


def _close_after_failure(
    trader_client: Any,
    md_client: Any,
    failure_cleanup: Callable[[], None] | None,
) -> bool:
    if failure_cleanup is None or not callable(failure_cleanup):
        return _close_both(trader_client, md_client)
    try:
        failure_cleanup()
    except BaseException:
        return False
    return True


def start_ctp_simnow_native_readiness(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowNativeStartupConfig,
    *,
    md_client_factory: Callable[[str, str, str, str], Any],
    market_client_sink: Callable[[Any], None],
    failure_cleanup: Callable[[], None] | None = None,
    timeout_seconds: float = 20.0,
    monotonic: Callable[[], float] = time.monotonic,
) -> CtpSimNowNativeReadiness:
    """Start one exact TD/MD pair and require a post-ACK matching first tick.

    ``trader_client`` is the unstarted public ``TraderClient`` instance already
    constructed by the caller's artifact-first composition. ``md_client_factory``
    constructs a fresh public ``MdClient`` using the exact selected MD front;
    ``market_client_sink`` hands ownership of the market client to the caller.
    A managed runtime passes ``failure_cleanup`` so startup failures close
    through its lease-aware, idempotent resource owner. The sink must be called
    synchronously before the MD client is started, and must not be retained or
    called after this readiness function returns. This function never
    looks at the client's private attributes and
    never invokes any order, cancel, authentication-write, or settlement-write
    operation. The SDK's start call still performs its ordinary session
    authentication/login sequence.
    """

    try:
        registration = _validate_inputs(
            trader_client,
            selection,
            config,
            md_client_factory,
            market_client_sink,
            timeout_seconds,
        )
        if failure_cleanup is not None and not callable(failure_cleanup):
            _reject("managed_simnow_failure_cleanup_invalid")
        if not callable(monotonic):
            _reject("managed_simnow_clock_invalid")
        deadline = float(monotonic()) + float(timeout_seconds)
        if not math.isfinite(deadline):
            _reject("managed_simnow_clock_invalid")
    except CtpSimNowNativeReadinessError as exc:
        closed = _close_after_failure(trader_client, None, failure_cleanup)
        raise CtpSimNowNativeReadinessError(
            exc.reason, close_state="closed" if closed else "close_failed"
        ) from None
    except Exception:
        closed = _close_after_failure(trader_client, None, failure_cleanup)
        raise CtpSimNowNativeReadinessError(
            "managed_simnow_initial_state_unavailable",
            close_state="closed" if closed else "close_failed",
        ) from None

    condition = threading.Condition()
    events: dict[str, Any] = {
        "error": None,
        "login_generation": None,
        "login_day": None,
        "subscription_requested": False,
        "subscription_generation": None,
        "subscription_acknowledged": False,
        "tick_observed": False,
    }
    md_client: Any = None
    failure: str | None = None
    pending_interrupt: BaseException | None = None

    def record_error(reason: str) -> None:
        with condition:
            if events["error"] is None:
                events["error"] = reason
            condition.notify_all()

    try:
        try:
            md_client = md_client_factory(
                registration.md_front,
                config.broker_id,
                config.user_id,
                config.password,
            )
        except Exception:
            _reject("managed_simnow_md_client_construction_failed")
        if md_client is None:
            _reject("managed_simnow_md_client_construction_failed")
        market_client_sink(md_client)
        for name in ("start", "stop", "subscribe"):
            if not callable(getattr(md_client, name, None)):
                _reject("managed_simnow_md_public_api_unavailable")
        if (
            getattr(md_client, "front", None) != registration.md_front
            or getattr(md_client, "broker_id", None) != config.broker_id
            or getattr(md_client, "user_id", None) != config.user_id
            or getattr(md_client, "is_ready", None) is not False
            or getattr(md_client, "connection_generation", None) != 0
            or getattr(md_client, "active_md_identity", None) is not None
        ):
            _reject("managed_simnow_md_client_not_fresh_or_scope_mismatch")
        for callback_name in ("on_login", "on_error", "on_disconnect", "on_subscribe", "on_tick"):
            if getattr(md_client, callback_name, None) is not None:
                _reject("managed_simnow_md_client_callbacks_already_bound")
        if not hasattr(md_client, "auto_resubscribe_on_login"):
            _reject("managed_simnow_md_resubscribe_control_unavailable")
        # Disable SDK-managed resubscription so there can be only one adapter
        # initiated subscription request, whose generation we can observe.
        md_client.auto_resubscribe_on_login = False

        def on_md_login(_login: Any) -> None:
            try:
                snapshot = _md_snapshot(md_client, config, registration)
                if snapshot is None:
                    record_error("managed_simnow_md_login_identity_unavailable")
                    return
                with condition:
                    prior = events["login_generation"]
                    if prior is not None and prior != snapshot.generation:
                        events["error"] = "managed_simnow_md_generation_changed"
                    else:
                        events["login_generation"] = snapshot.generation
                        events["login_day"] = snapshot.trading_day
                    condition.notify_all()
            except CtpSimNowNativeReadinessError as exc:
                record_error(exc.reason)
            except Exception:
                record_error("managed_simnow_md_login_callback_invalid")

        def on_md_error(info: Any) -> None:
            error_id = _error_id(info)
            if error_id != 0:
                record_error("managed_simnow_md_provider_error")

        def on_md_disconnect(_reason: Any) -> None:
            record_error("managed_simnow_md_disconnected")

        def on_md_subscribe(instrument_field: Any, response_info: Any) -> None:
            try:
                instrument = getattr(instrument_field, "InstrumentID")
            except Exception:
                record_error("managed_simnow_md_subscription_identity_unavailable")
                return
            if instrument != registration.instrument_id:
                return
            error_id = _error_id(response_info)
            if error_id != 0:
                record_error("managed_simnow_md_subscription_rejected")
                return
            try:
                snapshot = _md_snapshot(md_client, config, registration)
            except CtpSimNowNativeReadinessError as exc:
                record_error(exc.reason)
                return
            if snapshot is None:
                record_error("managed_simnow_md_subscription_generation_unavailable")
                return
            with condition:
                if not events["subscription_requested"]:
                    # An unsolicited ACK cannot prove the adapter's one
                    # explicit request was accepted.
                    return
                if snapshot.generation != events["login_generation"]:
                    events["error"] = "managed_simnow_md_generation_changed"
                elif events["subscription_acknowledged"]:
                    events["error"] = "managed_simnow_md_subscription_ack_duplicated"
                else:
                    events["subscription_acknowledged"] = True
                    events["subscription_generation"] = snapshot.generation
                condition.notify_all()

        def on_md_tick(tick: Any) -> None:
            if not _matching_tick(tick, registration):
                return
            try:
                snapshot = _md_snapshot(md_client, config, registration)
            except CtpSimNowNativeReadinessError as exc:
                record_error(exc.reason)
                return
            if snapshot is None:
                record_error("managed_simnow_md_tick_identity_unavailable")
                return
            with condition:
                if not events["subscription_acknowledged"]:
                    # Require a callback observed after the exact ACK.
                    return
                if (
                    snapshot.generation != events["login_generation"]
                    or snapshot.generation != events["subscription_generation"]
                ):
                    events["error"] = "managed_simnow_md_generation_changed"
                else:
                    events["tick_observed"] = True
                condition.notify_all()

        md_client.on_login = on_md_login
        md_client.on_error = on_md_error
        md_client.on_disconnect = on_md_disconnect
        md_client.on_subscribe = on_md_subscribe
        md_client.on_tick = on_md_tick

        # Mark each client as potentially live before entering public start:
        # the synchronous SDK call can fail after partially initializing native
        # state, so all failures below stop both constructed clients.
        trader_client.start(block=False)
        if float(monotonic()) >= deadline:
            _reject("managed_simnow_startup_deadline_expired")
        md_client.start(block=False)
        if float(monotonic()) >= deadline:
            _reject("managed_simnow_startup_deadline_expired")

        td_baseline: _TdSnapshot | None = None
        md_baseline: _MdSnapshot | None = None
        while True:
            now = float(monotonic())
            if not math.isfinite(now):
                _reject("managed_simnow_clock_invalid")
            if now >= deadline:
                _reject("managed_simnow_native_readiness_timeout")
            td_snapshot = _td_snapshot(trader_client, config, registration)
            md_snapshot = _md_snapshot(md_client, config, registration)
            if td_snapshot is not None:
                if td_baseline is None:
                    td_baseline = td_snapshot
                elif td_snapshot != td_baseline:
                    _reject("managed_simnow_td_generation_or_day_changed")
            if md_snapshot is not None:
                if md_baseline is None:
                    md_baseline = md_snapshot
                elif md_snapshot != md_baseline:
                    _reject("managed_simnow_md_generation_or_day_changed")
            if td_snapshot is not None and md_snapshot is not None:
                if td_snapshot.trading_day != md_snapshot.trading_day:
                    _reject("managed_simnow_trading_day_mismatch")
                with condition:
                    if events["login_generation"] is None:
                        events["login_generation"] = md_snapshot.generation
                        events["login_day"] = md_snapshot.trading_day
                    elif (
                        events["login_generation"] != md_snapshot.generation
                        or events["login_day"] != md_snapshot.trading_day
                    ):
                        events["error"] = "managed_simnow_md_generation_or_day_changed"
                    request_subscription = (
                        events["error"] is None and not events["subscription_requested"]
                    )
                    if request_subscription:
                        events["subscription_requested"] = True
                if request_subscription:
                    try:
                        # This is the sole explicit subscribe call for this
                        # adapter invocation. The SDK callback omits native
                        # request id/final-fragment fields, so a fresh client,
                        # disabled auto-resubscription and a single instrument
                        # are required to preserve correlation.
                        md_client.subscribe([registration.instrument_id])
                    except Exception:
                        _reject("managed_simnow_md_subscription_call_failed")
                with condition:
                    if events["error"] is not None:
                        _reject(str(events["error"]))
                    if events["subscription_acknowledged"] and events["tick_observed"]:
                        # Final public-state readback fences a disconnect or
                        # generation switch observed at the end of callbacks.
                        final_td = _td_snapshot(trader_client, config, registration)
                        final_md = _md_snapshot(md_client, config, registration)
                        if (
                            final_td != td_baseline
                            or final_md != md_baseline
                            or final_td is None
                            or final_md is None
                            or final_td.trading_day != final_md.trading_day
                            or events["subscription_generation"] != final_md.generation
                        ):
                            _reject("managed_simnow_final_readiness_scope_changed")
                        return CtpSimNowNativeReadiness(
                            config_digest=selection.config_digest,
                            registration_digest=registration.digest,
                            account_fingerprint_sha256=registration.account_fingerprint_sha256,
                            md_front=registration.md_front,
                            td_front=registration.td_front,
                            td_ready=True,
                            md_ready=True,
                        )
            with condition:
                if events["error"] is not None:
                    _reject(str(events["error"]))
                remaining = deadline - float(monotonic())
                if remaining <= 0:
                    _reject("managed_simnow_native_readiness_timeout")
                condition.wait(min(remaining, 0.05))
    except CtpSimNowNativeReadinessError as exc:
        failure = exc.reason
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            pending_interrupt = exc
        failure = "managed_simnow_native_startup_failed"

    closed = _close_after_failure(trader_client, md_client, failure_cleanup)
    if pending_interrupt is not None:
        raise pending_interrupt
    raise CtpSimNowNativeReadinessError(
        failure or "managed_simnow_native_startup_failed",
        close_state="closed" if closed else "close_failed",
    )


def stop_ctp_simnow_native_clients(trader_client: Any, md_client: Any) -> None:
    """Stop both successful-session clients; attempt both even if one fails."""

    if not _close_both(trader_client, md_client):
        raise CtpSimNowNativeReadinessError(
            "managed_simnow_native_close_failed", close_state="close_failed"
        )


__all__ = [
    "CtpSimNowNativeReadinessError",
    "CtpSimNowNativeStartupConfig",
    "start_ctp_simnow_native_readiness",
    "stop_ctp_simnow_native_clients",
]
