"""Coordinate Backtrader Store lifecycle without owning SDK transport state.

The Store owns its state, locks and callbacks; SDK components own workers,
subscriptions and bounded close. No second lifecycle state is retained here.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Optional


def stop_store(store, timeout: Optional[float] = None, *, safe_log):
    """Bound Store work and close only an API this Store owns."""
    managed_borrowed_api = store._managed_runtime_borrowed_api
    if managed_borrowed_api is not None:
        store._managed_runtime_stopped = True
        if store._api is not managed_borrowed_api:
            store._shutdown_state = "INCOMPLETE"
    store._signal_live_bar_event()
    deadline = time.monotonic() + (
        store._command_shutdown_timeout if timeout is None else max(float(timeout), 0.0)
    )
    # Fence funding publications before any early return.  The controller
    # owns direct and queued metadata reads even for read-only stores.
    store._signal_funding_refresh_stop()
    # A settlement authorization is a one-run opaque input and is never
    # retained across a Store stop, including an incomplete shutdown.
    store._settlement_authorization = None
    probe_owned_shutdown_pending = bool(
        store._metadata_probe_service.is_active()
        and not store._metadata_probe_service.owns_current_thread()
    )
    if probe_owned_shutdown_pending:
        # The bounded probe's worker may still be inside a synchronous SDK
        # read.  Closing the shared API concurrently could turn a read
        # timeout into an unknown transport state, so only its owner may
        # finish shutdown.  Callers receive an explicit incomplete state.
        funding_worker_stopped = store._stop_funding_refresh_worker(
            max(deadline - time.monotonic(), 0.0)
        )
        store._shutdown_state = "INCOMPLETE"
        store._command_health["read_only_metadata_probe_shutdown_blocked"] += 1
        if not funding_worker_stopped:
            store._command_health["funding_shutdown_blocked"] += 1
        return store.get_command_health()
    if store._service_read_only:
        funding_worker_stopped = store._stop_funding_refresh_worker(
            max(deadline - time.monotonic(), 0.0)
        )
        if not funding_worker_stopped:
            store._shutdown_state = "INCOMPLETE"
            store._command_health["funding_shutdown_blocked"] += 1
            store.emit_runtime_event(
                "store_disconnect_incomplete",
                status="incomplete",
                details={"reason": "funding_reader_still_active"},
            )
            return store.get_command_health()
        try:
            if store._api is not None and callable(getattr(store._api, "disconnect", None)):
                store._api.disconnect()
        except Exception:
            store._shutdown_state = "INCOMPLETE"
            store.emit_runtime_event(
                "store_disconnect_incomplete",
                status="incomplete",
                details={"reason": "service_facade_close_failed"},
            )
            raise
        store._connected = False
        store._started = False
        store._subscribed_datanames.clear()
        store._tick_consumers.clear()
        store._shutdown_state = "PASS"
        store._service_read_only_stopped = True
        store.emit_runtime_event("store_disconnected", status="disconnected")
        return store.get_command_health()
    with store._latest_tick_lock:
        store._latest_ticks.clear()
    if store._sdk_mode and not store.uses_async_commands:
        return store._stop_synchronous_sdk(max(deadline - time.monotonic(), 0.0))
    store._venue_balance_cache = {}
    partial_owned_sdk = store._sdk_mode and store._sdk_owned_api and store._api is not None
    partial_borrowed_sdk = managed_borrowed_api is not None
    command_state = store._command_runtime.snapshot()
    command_activity = bool(command_state.worker_alive or command_state.has_active_work)
    if (
        not store._connected
        and not store._started
        and not partial_owned_sdk
        and not partial_borrowed_sdk
        and not command_activity
        and not store._market_stream_adapter.has_subscriptions
    ):
        funding_worker_stopped = store._stop_funding_refresh_worker(
            max(deadline - time.monotonic(), 0.0)
        )
        if not funding_worker_stopped:
            store._shutdown_state = "INCOMPLETE"
            store._command_health["funding_shutdown_blocked"] += 1
        return store.get_command_health()

    worker_stopped = True
    if store._sdk_mode:
        store.freeze_openings("store_stop")
    if command_activity:
        drained = store.wait_for_commands(
            max(deadline - time.monotonic(), 0.0), stop_on_timeout=True
        )
        worker_stopped = store._stop_command_worker(
            max(deadline - time.monotonic(), 0.0),
            discard_pending=not drained,
        )
        if not drained or not worker_stopped:
            store._shutdown_state = "INCOMPLETE"

    # Metadata I/O has its own lane, so a slow funding endpoint cannot
    # delay cancellation/close processing above. It must nevertheless
    # finish before the shared SDK object can be closed or reused.
    funding_worker_stopped = store._stop_funding_refresh_worker(
        max(deadline - time.monotonic(), 0.0)
    )
    if not funding_worker_stopped:
        store._shutdown_state = "INCOMPLETE"

    market_stream_subscriptions_closed = True
    api_close_completed = store._api is None
    if managed_borrowed_api is not None:
        api_close_completed = store._api is managed_borrowed_api
    try:
        if store._connected:
            store.emit_runtime_event("store_disconnect_requested", status="disconnecting")

        if store._sdk_mode and store._market_stream_adapter.has_subscriptions:
            market_stream_subscriptions_closed = store._close_sdk_market_stream_subscriptions()
            if not market_stream_subscriptions_closed:
                store._shutdown_state = "INCOMPLETE"
                store.emit_runtime_event(
                    "store_disconnect_incomplete",
                    status="incomplete",
                    details={"reason": "sdk_market_stream_close_incomplete"},
                )

        if managed_borrowed_api is not None:
            try:
                store._unbind_live_bar_event_notifier()
            except BaseException:
                store._shutdown_state = "INCOMPLETE"
                raise

        if store._api is not None and funding_worker_stopped and market_stream_subscriptions_closed:
            if managed_borrowed_api is not None:
                # Store work is stopped, but the runtime owns API calls
                # and closes this exact object on its owner thread.
                api_close_completed = store._api is managed_borrowed_api
                if not api_close_completed:
                    store._shutdown_state = "INCOMPLETE"
            elif store._sdk_mode:
                store._cache_account_risk_snapshot_before_shutdown()
                try:
                    if hasattr(store._api, "get_execution_summary"):
                        store._last_execution_summary = deepcopy(
                            store._api.get_execution_summary()
                        )
                finally:
                    if worker_stopped:
                        stale_close_state = store._sdk_api_close_state
                        if stale_close_state is not None:
                            try:
                                store._close_stale_api_after_funding_timeout(
                                    stale_close_state["api"],
                                    allow_store_stopping=True,
                                    timeout=max(deadline - time.monotonic(), 0.0),
                                )
                            except Exception as exc:
                                safe_log("warning", "btapistore:stale_close_pending")
                                store.sanitize_exception(exc)
                                if store._shutdown_state != "FAIL":
                                    store._shutdown_state = "INCOMPLETE"
                            else:
                                api_close_completed = store._api is None
                        elif store._sdk_close_thread is not None:
                            # Do not issue a second close while a prior
                            # bounded close still owns this client, even
                            # if the first thread has just finished.
                            store._shutdown_state = "INCOMPLETE"
                            store._command_health["close_retry_blocked"] += 1
                        else:
                            closed, close_error = store._bounded_sdk_close(
                                store._api,
                                max(deadline - time.monotonic(), 0.0),
                            )
                            api_close_completed = bool(closed and close_error is None)
                            if not api_close_completed:
                                store._shutdown_state = (
                                    "INCOMPLETE" if not closed else "FAIL"
                                )
    finally:
        if store._sdk_mode:
            # An owned SDK that failed while closing is in an unknown
            # transport state and must never be reused on a later start.
            if (
                store._sdk_owned_api
                and worker_stopped
                and funding_worker_stopped
                and market_stream_subscriptions_closed
                and api_close_completed
            ):
                store._api = None
            if worker_stopped and funding_worker_stopped and market_stream_subscriptions_closed:
                store._sdk_configured = False
                # These bindings and queues describe one in-memory SDK session.
                store._clear_sdk_balance_snapshot()
                store._clear_sdk_order_correlations()
                store._execution_authorization = None
                store._settlement_authorization = None
                store._clear_sdk_updates("store_stopped")
                store._market_delivery_state.clear_book_drop_counts()
                store._market_delivery_state.clear_event_sequences()
                if not store._restart_blocked_by_close and store._shutdown_state not in {
                    "INCOMPLETE",
                    "FAIL",
                }:
                    store._shutdown_state = "PASS"
        elif worker_stopped:
            # Synchronous compatibility clients still use the Store's
            # worker solely for bounded command-completion delivery.
            store._clear_sdk_updates("store_stopped")
            if store._shutdown_state not in {"INCOMPLETE", "FAIL"}:
                store._shutdown_state = "PASS"
        if store._sdk_mode and not market_stream_subscriptions_closed:
            store._connected = True
        elif not store._sdk_mode and not worker_stopped:
            # A synchronous compatibility transport may still own an
            # active worker. Preserve the connection state while it runs.
            store.emit_runtime_event(
                "store_disconnect_incomplete",
                status="incomplete",
                details={"reason": "query_worker_still_running"},
            )
        else:
            store._connected = False
        store._started = False
        if market_stream_subscriptions_closed:
            store._subscribed_datanames.clear()
            store._tick_consumers.clear()
        if not store._connected:
            store.emit_runtime_event("store_disconnected", status="disconnected")
    return store.get_command_health()


def stop_synchronous_store_sdk(store, timeout: Optional[float] = None):
    """Preserve the pre-worker lifecycle for SDK-compatible fixture/legacy clients."""
    managed_borrowed_api = store._managed_runtime_borrowed_api
    if managed_borrowed_api is not None:
        store._managed_runtime_stopped = True
        if store._api is not managed_borrowed_api:
            store._shutdown_state = "INCOMPLETE"
    store._venue_balance_cache = {}
    store._clear_sdk_balance_snapshot()
    store._clear_sdk_order_correlations()
    store._execution_authorization = None
    store._settlement_authorization = None
    store._clear_sdk_updates("store_stopped")
    store._market_delivery_state.clear_book_drop_counts()
    funding_worker_stopped = store._stop_funding_refresh_worker(
        store._command_shutdown_timeout if timeout is None else timeout
    )
    partial_owned_sdk = store._sdk_owned_api and store._api is not None
    partial_borrowed_sdk = managed_borrowed_api is not None
    if (
        not store._connected
        and not store._started
        and not partial_owned_sdk
        and not partial_borrowed_sdk
        and not store._market_stream_adapter.has_subscriptions
    ):
        return store.get_command_health()
    market_stream_subscriptions_closed = True
    api_close_completed = store._api is None
    if managed_borrowed_api is not None:
        api_close_completed = store._api is managed_borrowed_api
    try:
        if store._connected:
            store.emit_runtime_event("store_disconnect_requested", status="disconnecting")
        if store._market_stream_adapter.has_subscriptions:
            market_stream_subscriptions_closed = store._close_sdk_market_stream_subscriptions()
            if not market_stream_subscriptions_closed:
                store._shutdown_state = "INCOMPLETE"
                store.emit_runtime_event(
                    "store_disconnect_incomplete",
                    status="incomplete",
                    details={"reason": "sdk_market_stream_close_incomplete"},
                )
        if managed_borrowed_api is not None:
            try:
                store._unbind_live_bar_event_notifier()
            except BaseException:
                store._shutdown_state = "INCOMPLETE"
                raise
        if store._api is not None and funding_worker_stopped and market_stream_subscriptions_closed:
            if managed_borrowed_api is not None:
                # Store work is stopped, but the runtime owns API calls
                # and closes this exact object on its owner thread.
                api_close_completed = store._api is managed_borrowed_api
                if not api_close_completed:
                    store._shutdown_state = "INCOMPLETE"
            else:
                try:
                    store._cache_account_risk_snapshot_before_shutdown()
                    if hasattr(store._api, "get_execution_summary"):
                        store._last_execution_summary = deepcopy(
                            store._api.get_execution_summary()
                        )
                finally:
                    closed, close_error = store._bounded_sdk_close(
                        store._api,
                        store._command_shutdown_timeout if timeout is None else timeout,
                    )
                    api_close_completed = bool(closed and close_error is None)
                    if not api_close_completed:
                        store._shutdown_state = "INCOMPLETE" if not closed else "FAIL"
    finally:
        if not funding_worker_stopped:
            store._shutdown_state = "INCOMPLETE"
        if (
            store._sdk_owned_api
            and funding_worker_stopped
            and market_stream_subscriptions_closed
            and api_close_completed
        ):
            store._api = None
        if funding_worker_stopped and market_stream_subscriptions_closed:
            store._sdk_configured = False
            if not store._restart_blocked_by_close and store._shutdown_state not in {
                "INCOMPLETE",
                "FAIL",
            }:
                store._shutdown_state = "PASS"
        if market_stream_subscriptions_closed:
            store._connected = False
        store._started = False
        if market_stream_subscriptions_closed:
            store._subscribed_datanames.clear()
            store._tick_consumers.clear()
            store.emit_runtime_event("store_disconnected", status="disconnected")
    return store.get_command_health()


def start_store(store, data=None, broker=None, *, error_type, gateway_entrypoint, gateway_error_type):
    """Start the store and attach broker/feed instances."""
    legacy_entrypoint = gateway_entrypoint(store.provider, store.backend)
    if legacy_entrypoint is not None:
        raise gateway_error_type(legacy_entrypoint)
    if store._managed_runtime_stopped:
        raise error_type("managed_runtime_store_session_already_stopped")
    if store._service_read_only_stopped:
        raise error_type("a stopped read-only service Store requires fresh client facades")
    if store._metadata_probe_service.is_active() and not store._metadata_probe_service.owns_current_thread():
        raise error_type(
            "Cannot start while a bounded read-only metadata probe owns the Store"
        )
    if data is not None and data not in store._data_feeds:
        store._data_feeds.append(data)
        attached_broker = broker if broker is not None else getattr(store, "_broker", None)
        hook = getattr(attached_broker, "data_started", None)
        if callable(hook):
            # The broker may hold restored orders waiting for this feed
            # (iteration 62 direct mode); other brokers ignore the hook.
            hook(data)
    if data is not None:
        env = getattr(data, "_env", None)
        if env is not None:
            store._env = store._cerebro = env

    if broker is not None:
        store._broker = broker

    if not store._started:
        if store._sdk_mode:
            # Validate command/stream/close readiness before the
            # funding controller is allowed to close a stale shared API.
            store._prepare_sdk_start()
        store._prepare_funding_refresh_start()
        command_state = store._command_runtime.snapshot()
        if not store._sdk_mode and command_state.restart_blocked_by_worker:
            if command_state.worker_alive:
                raise error_type(
                    "Cannot restart while the previous Store command worker is still running"
                )
            store._command_runtime.reset_after_recovery()
        with store._latest_tick_lock:
            store._latest_ticks.clear()
        if store._sdk_mode:
            store._reset_sdk_stream_generation()
        store._ensure_api_ready()
        if store.uses_async_commands:
            # Resolve the optional SDK models during startup. Importing
            # bt_api_py lazily on the first order can otherwise add tens
            # of milliseconds to the Cerebro submission path.
            store._sdk_correlated_order_adapter.warm_command_types()
            accept_openings = bool(
                not store.requires_account_risk
                and not store._execution_coordinator.risk_state_unknown
            )
            store._command_runtime.set_accept_openings(accept_openings)
            store._shutdown_state = "RUNNING"
            store._start_command_worker()
        store._started = True
        store._begin_funding_refresh_generation()


def prepare_store_sdk_start(store, *, error_type) -> None:
    """Reject restart while an earlier session worker can still mutate state."""
    if store._market_stream_adapter.has_subscriptions:
        store._restart_blocked_by_close = True
        raise error_type(
            "Cannot restart while a prior SDK market-stream subscription remains open"
        )
    pending_close = store._sdk_api_close_state
    if pending_close is not None:
        pending_api = pending_close.get("api")
        if pending_api is None:
            store._restart_blocked_by_close = True
            raise error_type("Cannot restart with an invalid SDK close outcome")
        closed, close_error = store._bounded_sdk_close(pending_api, 0.0)
        if not closed or close_error is not None:
            store._restart_blocked_by_close = True
            raise error_type("Cannot restart until the prior SDK close is verified")
        if store._api is pending_api:
            store._api = None
            store._sdk_configured = False
        elif store._api is not None:
            store._restart_blocked_by_close = True
            raise error_type("A different SDK API replaced the closed client")
    close_thread = store._sdk_close_thread
    if close_thread is not None and close_thread.is_alive():
        store._restart_blocked_by_close = True
        raise error_type(
            "Cannot restart while the previous SDK close callback is still running"
        )
    if close_thread is not None:
        # A thread without its retained API-bound outcome is not proof
        # that the client closed successfully.
        store._restart_blocked_by_close = True
        raise error_type("Cannot restart without a retained SDK close outcome")
    if store._restart_blocked_by_close:
        # With no close state/thread and no remaining market subscription (checked
        # above), the prior fence came from an open market stream that has
        # since completed its verified close.
        store._restart_blocked_by_close = False

    command_state = store._command_runtime.snapshot()
    if command_state.worker_alive:
        if command_state.restart_blocked_by_worker or command_state.stop_requested:
            raise error_type(
                "Cannot restart while the previous SDK command worker is still running"
            )
        return
    if not command_state.restart_blocked_by_worker:
        return

    stale_api = store._api if store._sdk_owned_api else None
    # A command-worker timeout does not grant this lane permission to
    # reuse or close the shared client while funding still has a read.
    if not store._stop_funding_refresh_worker(store._command_shutdown_timeout):
        raise error_type(
            "Cannot restart while a funding read still owns the SDK client"
        )
    if store._api is not None:
        store._assert_sdk_api_lanes_quiescent(store._api)
    if stale_api is not None:
        # Keep the command restart fence raised until the client close is
        # proven complete. A timeout leaves both gates in place for retry.
        store._close_stale_api_after_funding_timeout(stale_api)

    # The old worker has now exited, so its session-local identities can be
    # discarded before a new generation is allowed to begin.
    store._command_runtime.reset_after_recovery()
    store._clear_sdk_balance_snapshot()
    store._clear_sdk_order_correlations()
    store._market_delivery_state.clear_event_sequences()
    store._sdk_configured = False


def ensure_store_api_ready(store, *, error_type, gateway_entrypoint, gateway_error_type, placeholder_providers, provider_not_implemented_error_type, safe_log):
    """Instantiate and connect the underlying bt_api_py client on demand."""
    if (
        store._managed_runtime_borrowed_api is not None
        and store._managed_runtime_stopped
    ):
        raise error_type("managed_runtime_store_session_already_stopped")
    if (
        store._managed_runtime_borrowed_api is not None
        and store._api is not store._managed_runtime_borrowed_api
    ):
        raise error_type("managed_runtime_store_api_binding_changed")
    legacy_entrypoint = gateway_entrypoint(
        getattr(store, "provider", None), getattr(store, "backend", None)
    )
    if legacy_entrypoint is not None:
        raise gateway_error_type(legacy_entrypoint)
    metadata_probe_requires_market_data_only = (
        store._metadata_probe_service.requires_market_data_only
    )
    command_state = store._command_runtime.snapshot()
    if store._sdk_mode and (
        command_state.restart_blocked_by_worker or store._restart_blocked_by_close
    ):
        store._prepare_sdk_start()
    store._funding_refresh.prepare_if_restart_blocked()
    if store.provider in placeholder_providers:
        raise provider_not_implemented_error_type(
            f"provider '{store.provider}' is reserved for future bt_api_py support"
        )

    if store._api is None and not store._sdk_mode:
        raise error_type(
            "BtApiStore has no supported bt_api_py facade; provide an API instance, "
            "an api_cls factory, or explicit facade routes"
        )

    if store._connected:
        if store._sdk_mode and not store._service_read_only:
            store._assert_write_route_identity(require_live_route=True)
        store._bind_live_bar_event_notifier(store._api, store._signal_live_bar_event)
        return store._api

    if store._sdk_mode and not store._service_read_only:
        # Before a lazy factory runs, this validates only the explicit
        # Store route snapshot. _assert_write_route_identity checks the
        # facade's live route names again immediately after construction.
        store._assert_write_route_identity(require_live_route=True)

    if store._sdk_mode and not store._sdk_configured:
        if store._api is None:
            # Creating a fresh owned client starts a new SDK session even
            # when the caller connects lazily rather than through start().
            store._account_risk_state.reset_generation()
        assembly = store._ensure_sdk_direct_api_assembly()
        try:
            store._api = assembly.ensure_api()
        except BaseException as assembly_error:
            store._api = assembly.api
            assembly_code = getattr(assembly_error, "code", None)
            if assembly_code == "DIRECT_API_FACTORY_REUSED_CLOSED_INSTANCE":
                store._sdk_configured = False
                store._restart_blocked_by_close = True
                raise error_type(
                    "SDK factory returned a client instance that this Store already closed"
                ) from None
            if (
                assembly_code == "DIRECT_API_FACADE_INVALID"
                and store._sdk_owned_api
                and store._api is not None
            ):
                invalid_api = store._api
                closed, close_error = store._bounded_sdk_close(
                    invalid_api, store._command_shutdown_timeout
                )
                if not closed or close_error is not None:
                    store._shutdown_state = "INCOMPLETE" if not closed else "FAIL"
                    raise error_type(
                        "SDK factory returned an invalid facade and cleanup is unproven"
                    ) from None
                store._api = None
            raise
        if metadata_probe_requires_market_data_only:
            store._configure_bounded_metadata_probe_sdk_market_data_only()
        store._sdk_configured = True
        store._last_execution_summary = None

    if store._api is None:
        raise error_type(
            "BtApiStore cannot create a provider-specific client; use the "
            "bt_api_py unified facade with explicit exchange routes"
        )

    if store._sdk_mode and not store._service_read_only:
        # Validate the SDK's route-name projection before account/readiness
        # reads. BtApi constructs and configures its transports in its
        # constructor; the Store does not call a provider connect method.
        store._assert_write_route_identity(require_live_route=True)

    if (
        type(getattr(store._api, "service_read_only", None)) is bool
        and store._api.service_read_only is True
        and not store._service_read_only
    ):
        api = store._api
        if store._sdk_owned_api:
            closed, close_error = store._bounded_sdk_close(
                api, store._command_shutdown_timeout
            )
            if not closed or close_error is not None:
                store._shutdown_state = "INCOMPLETE" if not closed else "FAIL"
                raise error_type(
                    "read-only facade rejection cleanup is unproven"
                ) from None
            store._api = None
        raise error_type(
            "read-only service proxies must be injected with api= before Store creation"
        )

    if (
        store._sdk_mode
        and not metadata_probe_requires_market_data_only
        and not store._is_sdk_market_data_only()
        # Direct mode (iteration 62) has no SDK execution journal: durable
        # pending markers live in backtrader.live_state and BtApiBroker
        # reconciles them at start.
        and not getattr(store, "direct_write_mode", False)
    ):
        # The SDK hook only inspects its durable local journal and can
        # append a terminal event for the exact reservation-only pattern.
        # Run it before the Store starts its command worker.
        store._recover_sdk_startup_journal()

    store.emit_runtime_event("store_connecting", status="connecting")

    try:
        store._bind_live_bar_event_notifier(store._api, store._signal_live_bar_event)
        if store._service_read_only:
            store._api.connect()
    except Exception as exc:
        safe_log("error", "btapistore:14824 exception before re-raise (Exception)")
        store.sanitize_exception(exc)
        store.emit_runtime_event(
            "store_error",
            level="ERROR",
            status="connect_failed",
            error_code=type(exc).__name__,
            error_msg=str(exc),
        )
        raise

    store._connected = True
    if metadata_probe_requires_market_data_only:
        # Connection is an SDK lifecycle transition which may replace or
        # mutate its execution session.  Check raw public state before
        # Store's first balance/readiness query, then check once more in
        # the probe before its first typed metadata query.  The summary
        # remains an SDK evidence boundary rather than an unforgeable
        # receipt; arbitrary caller injection is rejected by the probe.
        store._verify_bounded_metadata_probe_sdk_market_data_only()
    if store._successful_connect_count > 0:
        store.emit_runtime_event("store_reconnect_success", status="connected")
    store._successful_connect_count += 1
    store.emit_runtime_event("store_connected", status="connected")
    try:
        if store._sdk_mode and getattr(store, "direct_write_mode", False):
            # Direct mode (iteration 62): BtApiBroker reads funds, positions
            # and working orders through the SDK direct account facts and
            # reconciles them with live_state before any write.
            pass
        elif store._sdk_mode and len(store._sdk_exchanges) > 1:
            # A multi-route Store has no scalar cash/equity contract.
            # Establish each configured account snapshot independently;
            # getcash/getvalue remain unavailable until a single-route
            # valuation is selected explicitly.
            store.get_venue_balances()
        else:
            store.get_balance()
    except Exception:
        store._connected = False
        if store._sdk_mode:
            api = store._api
            api_close_completed = api is None
            managed_borrowed_api = store._managed_runtime_borrowed_api
            if managed_borrowed_api is not None:
                store._managed_runtime_stopped = True
                store._shutdown_state = "INCOMPLETE"
                store._sdk_configured = False
                if api is managed_borrowed_api:
                    try:
                        store._unbind_live_bar_event_notifier()
                    except BaseException as cleanup_error:
                        store.sanitize_exception(cleanup_error)
                        raise error_type(
                            "managed runtime startup cleanup is unproven"
                        ) from cleanup_error
            else:
                try:
                    get_execution_summary = getattr(api, "get_execution_summary", None)
                    if callable(get_execution_summary):
                        store._last_execution_summary = deepcopy(get_execution_summary())
                except Exception:
                    # Execution auditing is best effort while preserving the
                    # original account-readiness failure for the caller.
                    safe_log("warning", "btapistore:14846 suppressed Exception")
                if api is not None:
                    closed, close_error = store._bounded_sdk_close(
                        api, store._command_shutdown_timeout
                    )
                    api_close_completed = bool(closed and close_error is None)
                    if closed and close_error is None:
                        store._shutdown_state = "PASS"
                    else:
                        store._shutdown_state = "INCOMPLETE" if not closed else "FAIL"
                if store._sdk_owned_api and api_close_completed:
                    store._api = None
            store._sdk_configured = False
        raise
    store.emit_runtime_event("store_ready", status="ready")
    return store._api


__all__ = (
    "start_store", "prepare_store_sdk_start", "ensure_store_api_ready",
    "stop_store", "stop_synchronous_store_sdk",
)
