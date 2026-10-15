"""Own one managed execution runtime for one Cerebro run.

The session is an explicit opt-in composition. Importing this module creates no
SDK runtime, transport, thread, or registration. A session owns the supplied
runtime after successful construction and consumes it on its first ``run``
attempt.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Optional

__all__ = [
    "ServiceExecutionSession",
    "ServiceExecutionSessionCleanupError",
    "ServiceExecutionSessionConfigError",
    "ServiceExecutionSessionError",
    "ServiceStrategyAccountBookRoute",
    "run_configured_cerebro",
]

_RUNTIME_OWNER_ATTRIBUTE = "_backtrader_service_execution_session_owner"
_RUNTIME_OWNER_LOCK = threading.Lock()
_WRITER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
_QUERY_OPERATIONS = frozenset({"orders.query"})
_ACCOUNT_BOOK_OPERATION = "execution.account_books.query"
_REPORT_UNSET = object()


@dataclass(frozen=True)
class ServiceStrategyAccountBookRoute:
    """One explicit strategy/account read route for a managed Cerebro run.

    ``owned=True`` transfers this runtime's start, renewal and close lifecycle
    to the session. A borrowed runtime must already be registered; its external
    owner remains responsible for renewal and close on the creating thread.
    The primary execution runtime passed to :class:`ServiceExecutionSession` is
    always owned by that session.
    """

    strategy_ref: str
    account_ref: str
    runtime: Any
    mount: str
    scope_ref: str
    owned: bool = True


class ServiceExecutionSessionError(RuntimeError):
    """Finite diagnostics for the explicit execution-session lifecycle."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ServiceExecutionSessionConfigError(ServiceExecutionSessionError, ValueError):
    """A session or runtime route does not satisfy the required contract."""


class ServiceExecutionSessionCleanupError(ServiceExecutionSessionError):
    """The run returned, but shutdown could not be certified as complete."""


@dataclass(frozen=True)
class ServiceExecutionCleanupReport:
    """Finite cleanup facts for this one session run."""

    state: str
    errors: tuple[str, ...]
    broker_stop_attempted: bool
    store_connected: Optional[bool]
    runtime_state: Optional[str]
    runtime_close_attempted: bool
    unregister_uncertainties: Optional[int]
    cleanup_failures: Optional[int]


class ServiceExecutionSession:
    """Bind an SDK execution runtime to one ``BtApiBroker`` and Cerebro run.

    The constructor only validates and assembles the SDK client and Backtrader
    adapter. The caller's explicit :meth:`run` starts registrations, validates
    public registered routes, and then enters Cerebro on the runtime's owner
    thread.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        mount: str,
        scope_ref: str,
        query_mount: str,
        query_scope_ref: str,
        refresh_interval_seconds: float = 1.0,
        max_refresh_interval_seconds: float = 30.0,
        backoff_factor: float = 2.0,
        limit: int = 32,
        monotonic_clock: Callable[[], float] = time.monotonic,
        strategy_account_book_routes: tuple[ServiceStrategyAccountBookRoute, ...] = (),
    ) -> None:
        _validate_refresh_settings(
            refresh_interval_seconds,
            max_refresh_interval_seconds,
            backoff_factor,
            limit,
            monotonic_clock,
        )
        try:
            from bt_api_py.service_execution import ServiceExecutionClient
            from bt_api_py.service_runtime import ServiceClientRuntime
        except ImportError as error:
            raise ServiceExecutionSessionConfigError("SERVICE_SDK_UNAVAILABLE") from error

        if not isinstance(runtime, ServiceClientRuntime):
            raise ServiceExecutionSessionConfigError("INVALID_RUNTIME")
        if runtime.state != "new":
            raise ServiceExecutionSessionConfigError("RUNTIME_NOT_NEW")
        try:
            runtime.next_maintenance_delay()
        except Exception:
            raise ServiceExecutionSessionConfigError("WRONG_RUNTIME_THREAD") from None

        try:
            client = ServiceExecutionClient(
                runtime,
                mount,
                scope_ref=scope_ref,
                query_mount=query_mount,
                query_scope_ref=query_scope_ref,
            )
            from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter

            adapter = ServiceExecutionAdapter(client)
        except Exception as error:
            code = _safe_code(error, "INVALID_EXECUTION_ROUTE")
            raise ServiceExecutionSessionConfigError(code) from None

        account_book_routes = _coerce_strategy_account_book_routes(
            runtime, strategy_account_book_routes, ServiceClientRuntime
        )
        owned_runtimes = _unique_owned_runtimes(runtime, account_book_routes)

        self.runtime = runtime
        self.client = client
        self.adapter = adapter
        self.mount = mount
        self.scope_ref = scope_ref
        self.query_mount = query_mount
        self.query_scope_ref = query_scope_ref
        self._creator_thread_id = threading.get_ident()
        self._refresh_interval_seconds = refresh_interval_seconds
        self._max_refresh_interval_seconds = max_refresh_interval_seconds
        self._backoff_factor = backoff_factor
        self._limit = limit
        self._monotonic_clock = monotonic_clock
        self._broker = None
        self._refresh_loop = None
        self._run_attempted = False
        self._broker_stop_attempted = False
        self._broker_stop_errors = []
        self._runtime_close_attempted = False
        self._account_book_route_specs = account_book_routes
        self._owned_runtimes = owned_runtimes
        self._runtime_start_attempted = set()
        self._account_book_route_views = MappingProxyType({})
        self._bound_strategy_views = {}
        self._strategy_route_owners = {}
        self._state = "new"
        self._cleanup_report = ServiceExecutionCleanupReport(
            state="new",
            errors=(),
            broker_stop_attempted=False,
            store_connected=None,
            runtime_state="new",
            runtime_close_attempted=False,
            unregister_uncertainties=0,
            cleanup_failures=0,
        )

        # The runtime itself is the ownership fence. It is never silently
        # borrowed or handed to a second Backtrader session.
        claimed = []
        with _RUNTIME_OWNER_LOCK:
            for owned_runtime in owned_runtimes:
                if owned_runtime.state != "new":
                    raise ServiceExecutionSessionConfigError("RUNTIME_NOT_NEW")
                if hasattr(owned_runtime, _RUNTIME_OWNER_ATTRIBUTE):
                    raise ServiceExecutionSessionConfigError("RUNTIME_ALREADY_OWNED")
            try:
                for owned_runtime in owned_runtimes:
                    setattr(owned_runtime, _RUNTIME_OWNER_ATTRIBUTE, self)
                    claimed.append(owned_runtime)
            except Exception:
                for owned_runtime in reversed(claimed):
                    try:
                        if getattr(owned_runtime, _RUNTIME_OWNER_ATTRIBUTE, None) is self:
                            delattr(owned_runtime, _RUNTIME_OWNER_ATTRIBUTE)
                    except Exception:
                        pass
                raise ServiceExecutionSessionConfigError("RUNTIME_OWNER_UNAVAILABLE") from None

    @property
    def state(self) -> str:
        """Return this session's finite lifecycle state."""

        return self._state

    @property
    def refresh_loop(self) -> Any:
        """Return the per-run refresh loop, or ``None`` before broker binding."""

        return self._refresh_loop

    @property
    def refresh_stats(self) -> Any:
        """Return the loop's immutable counters once the run has been bound."""

        return self._refresh_loop.stats if self._refresh_loop is not None else None

    def strategy_account_book_view(self, *, strategy_ref: str, account_ref: str) -> Any:
        """Return one explicit strategy/account view when the route opted in.

        The execution account-book operation is an optional capability on the
        existing ``broker.order_query`` mount. Runtime construction must
        explicitly request and receive that operation; ordinary execution
        sessions remain unchanged when it is absent.
        """

        self._assert_creator_thread()
        if self._state != "running" or self._broker is None:
            raise ServiceExecutionSessionError("SESSION_NOT_RUNNING")
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (strategy_ref, account_ref)
        ):
            raise ServiceExecutionSessionConfigError("INVALID_STRATEGY_ACCOUNT_SCOPE")
        view = self._account_book_route_views.get((strategy_ref, account_ref))
        if view is None:
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_ROUTE_UNAVAILABLE")
        return view

    def bind_strategy_account_book(
        self,
        strategy: Any,
        *,
        strategy_ref: str,
        account_ref: str,
    ) -> Any:
        """Attach the exact read route to one real Strategy using explicit IDs."""

        self._assert_creator_thread()
        if self._state != "running" or self._broker is None:
            raise ServiceExecutionSessionError("SESSION_NOT_RUNNING")
        try:
            from backtrader.strategy import Strategy
        except Exception:
            raise ServiceExecutionSessionConfigError("STRATEGY_TYPE_UNAVAILABLE") from None
        if not isinstance(strategy, Strategy):
            raise ServiceExecutionSessionConfigError("INVALID_STRATEGY_INSTANCE")
        if getattr(strategy, "broker", None) is not self._broker:
            raise ServiceExecutionSessionConfigError("STRATEGY_BROKER_MISMATCH")
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (strategy_ref, account_ref)
        ):
            raise ServiceExecutionSessionConfigError("INVALID_STRATEGY_ACCOUNT_SCOPE")
        params = getattr(strategy, "p", None)
        if (
            getattr(params, "strategy_ref", None) != strategy_ref
            or getattr(params, "account_ref", None) != account_ref
        ):
            raise ServiceExecutionSessionConfigError("STRATEGY_IDENTITY_MISMATCH")

        key = (strategy_ref, account_ref)
        view = self.strategy_account_book_view(
            strategy_ref=strategy_ref,
            account_ref=account_ref,
        )
        object_key = id(strategy)
        previous = self._bound_strategy_views.get(object_key)
        if previous is not None:
            previous_strategy, previous_key, previous_view = previous
            if previous_strategy is strategy and previous_key == key:
                return previous_view
            raise ServiceExecutionSessionConfigError("STRATEGY_ALREADY_BOUND")
        route_owner = self._strategy_route_owners.get(key)
        if route_owner is not None and route_owner is not strategy:
            raise ServiceExecutionSessionConfigError("STRATEGY_ROUTE_ALREADY_BOUND")
        existing_view = getattr(strategy, "account_book", None)
        if existing_view is not None and existing_view is not view:
            raise ServiceExecutionSessionConfigError("STRATEGY_ACCOUNT_BOOK_ALREADY_BOUND")
        try:
            strategy.account_book = view
        except Exception:
            raise ServiceExecutionSessionConfigError("STRATEGY_ACCOUNT_BOOK_BIND_FAILED") from None
        self._bound_strategy_views[object_key] = (strategy, key, view)
        self._strategy_route_owners[key] = strategy
        return view

    def strategy_order_route_error(self, order: Any) -> Optional[str]:
        """Return a finite rejection code if an explicit Strategy has another writer scope."""

        self._assert_creator_thread()
        if self._state != "running":
            return None
        owner = getattr(order, "owner", None)
        if owner is None:
            return None
        params = getattr(owner, "p", None)
        strategy_ref = getattr(params, "strategy_ref", None)
        account_ref = getattr(params, "account_ref", None)
        bound = self._bound_strategy_views.get(id(owner))
        if strategy_ref is None and account_ref is None:
            if bound is not None:
                return "strategy_writer_identity_incomplete"
            account_book = getattr(owner, "account_book", None)
            if account_book is not None and any(
                account_book is view for view in self._account_book_route_views.values()
            ):
                return "strategy_writer_strategy_not_bound"
            return None
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (strategy_ref, account_ref)
        ):
            return "strategy_writer_identity_incomplete"
        key = (strategy_ref, account_ref)
        if key != self._writer_scope_identity:
            return "strategy_writer_route_mismatch"
        if key in self._account_book_route_views:
            if bound is None:
                return "strategy_writer_strategy_not_bound"
            bound_strategy, bound_key, bound_view = bound
            if (
                bound_strategy is not owner
                or bound_key != key
                or getattr(owner, "account_book", None) is not bound_view
                or self._strategy_route_owners.get(key) is not owner
            ):
                return "strategy_writer_route_mismatch"
        return None

    @property
    def cleanup_report(self) -> ServiceExecutionCleanupReport:
        """Return the latest finite shutdown report."""

        return self._cleanup_report

    def run(self, cerebro: Any, **run_kwargs: Any) -> Any:
        """Run one Cerebro instance, owning startup and reporting cleanup."""

        self._assert_creator_thread()
        if self._run_attempted:
            raise ServiceExecutionSessionError("SESSION_ALREADY_USED")
        self._run_attempted = True
        self._state = "preflight"

        try:
            broker, store = self._preflight(cerebro, run_kwargs)
        except BaseException:
            ownership_errors = self._release_runtime_ownership()
            self._state = "close_failed" if ownership_errors else "rejected"
            self._record_report(
                errors=("PREFLIGHT_REJECTED", *ownership_errors),
                store_connected=None,
                runtime_close_attempted=False,
            )
            raise

        # Cerebro's documented no-data behavior is an empty result. Consume the
        # session but do not attach it or start/close a runtime with no work.
        if not cerebro.datas and run_kwargs.get("channel") is None:
            ownership_errors = self._release_runtime_ownership()
            self._state = "close_failed" if ownership_errors else "closed_unstarted"
            self._record_report(
                errors=ownership_errors,
                store_connected=False,
                runtime_close_attempted=False,
            )
            if ownership_errors:
                raise ServiceExecutionSessionCleanupError("SESSION_CLEANUP_UNCERTAIN")
            return []

        try:
            from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

            refresh_loop = ManagedOrderRefreshLoop(
                broker,
                interval_seconds=self._refresh_interval_seconds,
                max_interval_seconds=self._max_refresh_interval_seconds,
                backoff_factor=self._backoff_factor,
                limit=self._limit,
                monotonic_clock=self._monotonic_clock,
            )
        except BaseException:
            ownership_errors = self._release_runtime_ownership()
            self._state = "close_failed" if ownership_errors else "rejected"
            self._record_report(
                errors=("REFRESH_LOOP_SETUP_FAILED", *ownership_errors),
                store_connected=False,
                runtime_close_attempted=False,
            )
            raise
        self._refresh_loop = refresh_loop
        result = None
        primary_error = None
        cleanup_exception = None
        self._state = "starting"
        try:
            broker.attach_service_execution_session(self)
            store.attach_managed_execution_adapter(self.adapter)
            for owned_runtime in self._owned_runtimes:
                self._runtime_start_attempted.add(id(owned_runtime))
                owned_runtime.start()
            self._validate_registered_routes()
            self._validate_strategy_account_book_routes()
            self._state = "running"
            result = cerebro.run(**run_kwargs)
        except BaseException as error:
            primary_error = error
        finally:
            cleanup_errors = list(self._broker_stop_errors)
            if self._broker is broker and not self._broker_stop_attempted:
                try:
                    broker.stop()
                except BaseException as error:
                    cleanup_errors.append(_safe_code(error, "BROKER_STOP_FAILED"))
                    cleanup_exception = error
            cleanup_errors.extend(self._broker_stop_errors)
            try:
                store_connected = bool(store.is_connected)
            except BaseException as error:
                store_connected = None
                cleanup_errors.append("STORE_STATE_UNAVAILABLE")
                if cleanup_exception is None:
                    cleanup_exception = error
            if self._broker_stop_attempted and store_connected is True:
                cleanup_errors.extend(("BROKER_STOP_FAILED", "STORE_STILL_CONNECTED"))
            self._runtime_close_attempted = True
            # Ownership transferred for every owned route at construction.
            # Close even an owned runtime whose start was not reached after a
            # prior runtime failed; borrowed runtimes are absent from this list.
            close_candidates = self._owned_runtimes
            for owned_runtime in reversed(close_candidates):
                try:
                    owned_runtime.close()
                except BaseException as error:
                    if owned_runtime is self.runtime:
                        cleanup_errors.append(_safe_code(error, "RUNTIME_CLOSE_FAILED"))
                    else:
                        cleanup_errors.append("ACCOUNT_BOOK_RUNTIME_CLOSE_FAILED")
                    if cleanup_exception is None:
                        cleanup_exception = error

            runtime_state = _safe_runtime_state(self.runtime)
            all_runtime_states = tuple(
                _safe_runtime_state(owned_runtime) for owned_runtime in close_candidates
            )
            runtime_metrics = tuple(
                tuple(
                    _safe_runtime_metric(owned_runtime, metric_name)
                    for metric_name in ("unregister_uncertainties", "cleanup_failures")
                )
                for owned_runtime in close_candidates
            )
            unregister_values = tuple(metrics[0] for metrics in runtime_metrics)
            cleanup_values = tuple(metrics[1] for metrics in runtime_metrics)
            unregister_uncertainties = (
                sum(unregister_values)
                if all(value is not None for value in unregister_values)
                else None
            )
            cleanup_failures = (
                sum(cleanup_values) if all(value is not None for value in cleanup_values) else None
            )
            if runtime_state == "close_failed":
                cleanup_errors.append("RUNTIME_CLOSE_FAILED")
            if any(
                state == "close_failed"
                for managed_runtime, state in zip(close_candidates, all_runtime_states)
                if managed_runtime is not self.runtime
            ):
                cleanup_errors.append("ACCOUNT_BOOK_RUNTIME_CLOSE_FAILED")
            if unregister_uncertainties is not None and unregister_uncertainties > 0:
                cleanup_errors.append("UNREGISTER_UNCERTAIN")

            unique_errors = tuple(dict.fromkeys(cleanup_errors))
            hard_cleanup_errors = any(error != "UNREGISTER_UNCERTAIN" for error in unique_errors)
            if (
                store_connected is True
                or runtime_state == "close_failed"
                or "RUNTIME_CLOSE_FAILED" in unique_errors
                or "STORE_STATE_UNAVAILABLE" in unique_errors
                or "STORE_STILL_CONNECTED" in unique_errors
                or hard_cleanup_errors
            ):
                final_state = "close_failed"
            elif unregister_uncertainties is not None and unregister_uncertainties > 0:
                final_state = "closed_with_uncertainty"
            else:
                final_state = "closed"
            self._state = final_state
            self._record_report(
                errors=unique_errors,
                store_connected=store_connected,
                runtime_state=runtime_state,
                unregister_uncertainties=unregister_uncertainties,
                cleanup_failures=cleanup_failures,
                runtime_close_attempted=True,
            )

        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__)
        if cleanup_exception is not None:
            raise cleanup_exception.with_traceback(cleanup_exception.__traceback__)
        if self._cleanup_report.errors:
            raise ServiceExecutionSessionCleanupError("SESSION_CLEANUP_UNCERTAIN")
        return result

    def poll(self, broker: Any) -> tuple[Any, ...]:
        """Maintain runtime leases, then drive one due managed-order refresh."""

        self._assert_creator_thread()
        if (
            broker is not self._broker
            or self._state != "running"
            or self._broker_stop_attempted
            or self._refresh_loop is None
        ):
            raise ServiceExecutionSessionError("SESSION_NOT_RUNNING")
        for owned_runtime in self._owned_runtimes:
            if id(owned_runtime) in self._runtime_start_attempted:
                owned_runtime.maintain()
        return self._refresh_loop.run_once()

    def broker_starting(self, broker: Any) -> None:
        """Fence direct Broker.start calls to the active owning session."""

        self._assert_creator_thread()
        if (
            broker is not self._broker
            or self._state != "running"
            or self._broker_stop_attempted
            or _safe_runtime_state(self.runtime) != "registered"
        ):
            raise ServiceExecutionSessionError("SESSION_NOT_ACTIVE")

    def broker_stopping(self, broker: Any) -> None:
        """Record a stop attempt without changing the Broker's stop behavior."""

        if broker is self._broker:
            self._assert_creator_thread()
            self._broker_stop_attempted = True

    def broker_stop_failed(self, broker: Any, error: BaseException) -> None:
        """Retain a failed stop result without asking the Broker to stop again."""

        if broker is self._broker:
            self._broker_stop_errors.append(_safe_code(error, "BROKER_STOP_FAILED"))

    def broker_stopped(self, broker: Any, result: Any) -> None:
        """Record finite shutdown status from this exact Broker.stop call."""

        if broker is not self._broker or not isinstance(result, dict):
            return
        for key, error_code in (
            ("status", "BROKER_STOP_NOT_PASS"),
            ("shutdown_state", "STORE_SHUTDOWN_NOT_PASS"),
        ):
            status = result.get(key)
            if status is not None and status != "PASS":
                self._broker_stop_errors.append(error_code)

    def _bind_broker(self, broker: Any) -> None:
        self._assert_creator_thread()
        if self._run_attempted is not True or self._state != "starting":
            raise ServiceExecutionSessionError("SESSION_NOT_ATTACHABLE")
        if self._broker is not None:
            raise ServiceExecutionSessionError("BROKER_ALREADY_BOUND")
        self._broker = broker

    def _preflight(self, cerebro: Any, run_kwargs: dict[str, Any]) -> tuple[Any, Any]:
        self._assert_creator_thread()
        if _safe_runtime_state(self.runtime) != "new":
            raise ServiceExecutionSessionConfigError("RUNTIME_NOT_NEW")
        if "channel" in run_kwargs and run_kwargs["channel"] is not None:
            raise ServiceExecutionSessionConfigError("CHANNEL_MODE_UNSUPPORTED")
        if bool(getattr(cerebro, "_dooptimize", False)):
            raise ServiceExecutionSessionConfigError("OPTIMIZATION_UNSUPPORTED")

        from backtrader.brokers.btapibroker import BtApiBroker
        from backtrader.cerebro import Cerebro
        from backtrader.stores.btapistore import BtApiStore

        if not isinstance(cerebro, Cerebro):
            raise ServiceExecutionSessionConfigError("INVALID_CEREBRO")
        broker = cerebro.getbroker()
        if not isinstance(broker, BtApiBroker):
            raise ServiceExecutionSessionConfigError("INVALID_BROKER")
        if broker.store is None or not isinstance(broker.store, BtApiStore):
            raise ServiceExecutionSessionConfigError("INVALID_STORE")
        store = broker.store
        if getattr(cerebro, "_broker", None) is not broker:
            raise ServiceExecutionSessionConfigError("BROKER_MISMATCH")
        if bool(getattr(store, "_service_read_only", False)):
            raise ServiceExecutionSessionConfigError("READ_ONLY_SERVICE_UNSUPPORTED")
        if broker._is_market_data_only():
            raise ServiceExecutionSessionConfigError("MARKET_DATA_ONLY_UNSUPPORTED")
        if (
            bool(getattr(broker, "_live_started", False))
            or bool(getattr(broker, "_startup_ready", False))
            or bool(getattr(store, "_started", False))
            or bool(store.is_connected)
            or bool(store.managed_execution_active)
            or getattr(store, "_cerebro_managed_lifecycle", True) is False
            or getattr(broker, "_service_execution_session", None) is not None
        ):
            raise ServiceExecutionSessionConfigError("BROKER_OR_STORE_ALREADY_ACTIVE")
        if not callable(getattr(broker, "attach_service_execution_session", None)):
            raise ServiceExecutionSessionConfigError("BROKER_SESSION_HOOK_UNAVAILABLE")
        return broker, store

    def _validate_registered_routes(self) -> None:
        from bt_api_base.service_protocol import WireScope

        try:
            if _safe_runtime_state(self.runtime) != "registered":
                raise ServiceExecutionSessionConfigError("RUNTIME_NOT_REGISTERED")
            bindings = self.runtime.bindings
        except ServiceExecutionSessionConfigError:
            raise
        except Exception:
            raise ServiceExecutionSessionConfigError("RUNTIME_BINDINGS_UNAVAILABLE") from None
        if type(bindings) is not tuple:
            raise ServiceExecutionSessionConfigError("RUNTIME_BINDINGS_INVALID")

        writer = _unique_active_route(bindings, self.mount, self.scope_ref, _WRITER_OPERATIONS)
        query = _unique_active_route(
            bindings, self.query_mount, self.query_scope_ref, _QUERY_OPERATIONS
        )
        writer_scope = getattr(writer, "scope", None)
        query_scope = getattr(query, "scope", None)
        if type(writer_scope) is not WireScope or type(query_scope) is not WireScope:
            raise ServiceExecutionSessionConfigError("RUNTIME_SCOPE_INVALID")
        if writer_scope != query_scope:
            raise ServiceExecutionSessionConfigError("EXECUTION_QUERY_SCOPE_MISMATCH")
        for field in ("account_ref", "strategy_ref"):
            value = getattr(writer_scope, field, None)
            if type(value) is not str or not value:
                raise ServiceExecutionSessionConfigError("EXECUTION_SCOPE_INCOMPLETE")
        self._writer_scope_identity = (writer_scope.strategy_ref, writer_scope.account_ref)

    def _validate_strategy_account_book_routes(self) -> None:
        from bt_api_base.service_protocol import WireScope

        from backtrader.stores.service_strategy_account_book import (
            ServiceStrategyAccountBookView,
        )

        resolved = {}
        try:
            primary_bindings = self.runtime.bindings
        except Exception:
            raise ServiceExecutionSessionConfigError("RUNTIME_BINDINGS_UNAVAILABLE") from None
        if type(primary_bindings) is not tuple:
            raise ServiceExecutionSessionConfigError("RUNTIME_BINDINGS_INVALID")
        try:
            primary_binding = _unique_active_route(
                primary_bindings,
                self.query_mount,
                self.query_scope_ref,
                frozenset({_ACCOUNT_BOOK_OPERATION}),
            )
        except ServiceExecutionSessionConfigError as error:
            if error.code not in {
                "RUNTIME_ROUTE_OPERATION_MISSING",
                "RUNTIME_ROUTE_MISSING_OR_AMBIGUOUS",
            }:
                raise
        else:
            scope = _strategy_account_book_scope(primary_binding, WireScope)
            key = (scope.strategy_ref, scope.account_ref)
            resolved[key] = (
                self.runtime,
                self.query_mount,
                self.query_scope_ref,
            )

        for route in self._account_book_route_specs:
            if route.runtime.state != "registered":
                raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_RUNTIME_NOT_REGISTERED")
            try:
                bindings = route.runtime.bindings
            except Exception:
                raise ServiceExecutionSessionConfigError(
                    "ACCOUNT_BOOK_RUNTIME_BINDINGS_UNAVAILABLE"
                ) from None
            if type(bindings) is not tuple:
                raise ServiceExecutionSessionConfigError("RUNTIME_BINDINGS_INVALID")
            try:
                binding = _unique_active_route(
                    bindings,
                    route.mount,
                    route.scope_ref,
                    frozenset({_ACCOUNT_BOOK_OPERATION}),
                )
            except ServiceExecutionSessionConfigError as error:
                raise ServiceExecutionSessionConfigError(
                    "ACCOUNT_BOOK_ROUTE_UNAVAILABLE"
                ) from error
            scope = _strategy_account_book_scope(binding, WireScope)
            if scope.strategy_ref != route.strategy_ref or scope.account_ref != route.account_ref:
                raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_SCOPE_MISMATCH")
            key = (route.strategy_ref, route.account_ref)
            if key in resolved:
                raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_ROUTE_AMBIGUOUS")
            resolved[key] = (route.runtime, route.mount, route.scope_ref)

        self._account_book_route_views = MappingProxyType(
            {
                key: ServiceStrategyAccountBookView(
                    runtime,
                    mount=mount,
                    scope_ref=scope_ref,
                    strategy_ref=key[0],
                    account_ref=key[1],
                )
                for key, (runtime, mount, scope_ref) in resolved.items()
            }
        )

    def _record_report(
        self,
        *,
        errors: tuple[str, ...],
        store_connected: Optional[bool],
        runtime_state: Optional[str] = None,
        unregister_uncertainties: Any = _REPORT_UNSET,
        cleanup_failures: Any = _REPORT_UNSET,
        runtime_close_attempted: bool,
    ) -> None:
        if runtime_state is None:
            runtime_state = _safe_runtime_state(self.runtime)
        if unregister_uncertainties is _REPORT_UNSET:
            unregister_uncertainties = _safe_runtime_metric(
                self.runtime, "unregister_uncertainties"
            )
        if cleanup_failures is _REPORT_UNSET:
            cleanup_failures = _safe_runtime_metric(self.runtime, "cleanup_failures")
        self._cleanup_report = ServiceExecutionCleanupReport(
            state=self._state,
            errors=errors,
            broker_stop_attempted=self._broker_stop_attempted,
            store_connected=store_connected,
            runtime_state=runtime_state,
            runtime_close_attempted=runtime_close_attempted,
            unregister_uncertainties=unregister_uncertainties,
            cleanup_failures=cleanup_failures,
        )

    def _assert_creator_thread(self) -> None:
        if threading.get_ident() != self._creator_thread_id:
            raise ServiceExecutionSessionError("WRONG_SESSION_THREAD")

    def _release_runtime_ownership(self) -> tuple[str, ...]:
        """Release owned-runtime fences when this run never reached startup."""

        errors = []
        with _RUNTIME_OWNER_LOCK:
            for runtime in reversed(self._owned_runtimes):
                try:
                    if getattr(runtime, _RUNTIME_OWNER_ATTRIBUTE, None) is self:
                        delattr(runtime, _RUNTIME_OWNER_ATTRIBUTE)
                except Exception:
                    errors.append("RUNTIME_OWNER_RELEASE_FAILED")
        return tuple(dict.fromkeys(errors))


def run_configured_cerebro(
    cerebro: Any,
    client_config: Any = None,
    *,
    runtime_factory: Optional[Callable[[Any], Any]] = None,
    session_options: Optional[dict[str, Any]] = None,
    **run_kwargs: Any,
) -> Any:
    """Run ordinary Cerebro directly or through one configured execution session.

    ``client_config`` is an already-decoded plain-data dict accepted by the
    SDK's ``parse_client_config``.  The managed entry intentionally supports only a
    strategy client with exactly two required execution bindings:
    ``broker.orders`` and ``broker.order_query``.  Trusted deployment code
    supplies ``runtime_factory``; configuration never imports code or resolves
    identities, scopes, peers, or transport credentials by itself.

    Passing ``None`` preserves the ordinary ``cerebro.run`` path.  Once a
    configuration is supplied, parse, route, factory, and session errors
    propagate without falling back to an unmanaged run.
    """

    if client_config is None:
        return cerebro.run(**run_kwargs)

    try:
        from bt_api_py.service_config import parse_client_config
    except ImportError as error:
        raise ServiceExecutionSessionConfigError("SERVICE_SDK_UNAVAILABLE") from error

    parsed = parse_client_config(client_config)
    execution = _configured_execution_routes(parsed)
    if not callable(runtime_factory):
        raise ServiceExecutionSessionConfigError("RUNTIME_FACTORY_REQUIRED")
    options = {} if session_options is None else session_options
    if type(options) is not dict:
        raise ServiceExecutionSessionConfigError("INVALID_SESSION_OPTIONS")
    supported_options = {
        "refresh_interval_seconds",
        "max_refresh_interval_seconds",
        "backoff_factor",
        "limit",
        "monotonic_clock",
    }
    if set(options) - supported_options:
        raise ServiceExecutionSessionConfigError("UNSUPPORTED_SESSION_OPTION")

    runtime = runtime_factory(parsed)
    session = ServiceExecutionSession(
        runtime,
        mount="broker.orders",
        scope_ref=execution["broker.orders"]["scope_ref"],
        query_mount="broker.order_query",
        query_scope_ref=execution["broker.order_query"]["scope_ref"],
        **options,
    )
    return session.run(cerebro, **run_kwargs)


def _configured_execution_routes(parsed: Any) -> dict[str, dict[str, str]]:
    """Validate the deliberately narrow configuration subset used above."""

    if getattr(parsed, "process_role", None) != "strategy_client":
        raise ServiceExecutionSessionConfigError("UNSUPPORTED_CLIENT_ROLE")
    clients = getattr(parsed, "clients", None)
    if not isinstance(clients, Mapping):
        raise ServiceExecutionSessionConfigError("CLIENTS_UNAVAILABLE")
    if set(clients.keys()) != {"execution"}:
        raise ServiceExecutionSessionConfigError("UNSUPPORTED_CLIENT_SET")

    execution = clients.get("execution")
    settings = execution.get("settings") if isinstance(execution, Mapping) else None
    bindings = settings.get("bindings") if isinstance(settings, Mapping) else None
    if type(bindings) is not tuple or len(bindings) != 2:
        raise ServiceExecutionSessionConfigError("UNSUPPORTED_EXECUTION_BINDINGS")

    by_mount: dict[str, Any] = {}
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ServiceExecutionSessionConfigError("INVALID_EXECUTION_BINDING")
        mount = binding.get("mount")
        if mount not in {"broker.orders", "broker.order_query"} or mount in by_mount:
            raise ServiceExecutionSessionConfigError("UNSUPPORTED_EXECUTION_BINDINGS")
        by_mount[mount] = binding

    if set(by_mount) != {"broker.orders", "broker.order_query"}:
        raise ServiceExecutionSessionConfigError("UNSUPPORTED_EXECUTION_BINDINGS")
    shared_fields = ("service_id", "instance_id", "account_ref", "transport_ref")
    writer = by_mount["broker.orders"]
    query = by_mount["broker.order_query"]
    if any(
        type(writer.get(field)) is not str
        or not writer.get(field)
        or writer.get(field) != query.get(field)
        for field in shared_fields
    ):
        raise ServiceExecutionSessionConfigError("EXECUTION_BINDING_MISMATCH")

    routes = {}
    for mount, binding in by_mount.items():
        scope_ref = binding.get("scope_ref")
        if binding.get("required") is not True or type(scope_ref) is not str or not scope_ref:
            raise ServiceExecutionSessionConfigError("EXECUTION_BINDING_NOT_REQUIRED")
        routes[mount] = {"scope_ref": scope_ref}
    return routes


def _validate_refresh_settings(
    interval: Any,
    maximum: Any,
    backoff: Any,
    limit: Any,
    clock: Any,
) -> None:
    if type(limit) is not int or limit <= 0:
        raise ServiceExecutionSessionConfigError("INVALID_LIMIT")
    if not callable(clock):
        raise ServiceExecutionSessionConfigError("INVALID_CLOCK")
    if not _positive_finite(interval) or not _positive_finite(maximum):
        raise ServiceExecutionSessionConfigError("INVALID_INTERVAL")
    if _as_finite_float(maximum) < _as_finite_float(interval):
        raise ServiceExecutionSessionConfigError("INVALID_INTERVAL")
    if not _finite_number(backoff) or _as_finite_float(backoff) < 1:
        raise ServiceExecutionSessionConfigError("INVALID_BACKOFF")


def _coerce_strategy_account_book_routes(
    primary_runtime: Any,
    routes: tuple[ServiceStrategyAccountBookRoute, ...],
    runtime_type: type,
) -> tuple[ServiceStrategyAccountBookRoute, ...]:
    if type(routes) is not tuple:
        raise ServiceExecutionSessionConfigError("INVALID_ACCOUNT_BOOK_ROUTES")
    seen_pairs = set()
    runtime_modes = {}
    for route in routes:
        if type(route) is not ServiceStrategyAccountBookRoute:
            raise ServiceExecutionSessionConfigError("INVALID_ACCOUNT_BOOK_ROUTE")
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (
                route.strategy_ref,
                route.account_ref,
                route.mount,
                route.scope_ref,
            )
        ):
            raise ServiceExecutionSessionConfigError("INVALID_ACCOUNT_BOOK_ROUTE")
        if type(route.owned) is not bool or not isinstance(route.runtime, runtime_type):
            raise ServiceExecutionSessionConfigError("INVALID_ACCOUNT_BOOK_ROUTE")
        pair = (route.strategy_ref, route.account_ref)
        if pair in seen_pairs:
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_ROUTE_AMBIGUOUS")
        seen_pairs.add(pair)

        runtime = route.runtime
        runtime_id = id(runtime)
        previous_mode = runtime_modes.get(runtime_id)
        if previous_mode is not None and previous_mode != route.owned:
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_RUNTIME_OWNERSHIP_MISMATCH")
        runtime_modes[runtime_id] = route.owned
        if runtime is primary_runtime:
            if not route.owned:
                raise ServiceExecutionSessionConfigError("PRIMARY_RUNTIME_MUST_BE_OWNED")
            continue
        expected_state = "new" if route.owned else "registered"
        if runtime.state != expected_state:
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_RUNTIME_STATE_INVALID")
        if hasattr(runtime, _RUNTIME_OWNER_ATTRIBUTE):
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_RUNTIME_ALREADY_OWNED")
        try:
            runtime.next_maintenance_delay()
        except Exception:
            raise ServiceExecutionSessionConfigError("WRONG_RUNTIME_THREAD") from None
    return routes


def _unique_owned_runtimes(
    primary_runtime: Any,
    routes: tuple[ServiceStrategyAccountBookRoute, ...],
) -> tuple[Any, ...]:
    ordered = [primary_runtime]
    seen = {id(primary_runtime)}
    for route in routes:
        if route.owned and id(route.runtime) not in seen:
            ordered.append(route.runtime)
            seen.add(id(route.runtime))
    return tuple(ordered)


def _strategy_account_book_scope(binding: Any, wire_scope_type: type) -> Any:
    scope = getattr(binding, "scope", None)
    if type(scope) is not wire_scope_type:
        raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_SCOPE_INVALID")
    for name in ("strategy_ref", "account_ref"):
        value = getattr(scope, name, None)
        if type(value) is not str or not value or value != value.strip():
            raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_SCOPE_INVALID")
    if any(
        getattr(scope, name, None)
        for name in ("account_refs", "manual_book_ref", "portfolio_ref", "group_id", "leg_id")
    ):
        raise ServiceExecutionSessionConfigError("ACCOUNT_BOOK_SCOPE_INVALID")
    return scope


def _positive_finite(value: Any) -> bool:
    return _finite_number(value) and _as_finite_float(value) > 0


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _as_finite_float(value: Any) -> float:
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        return math.inf
    return converted if math.isfinite(converted) else math.inf


def _unique_active_route(
    bindings: tuple[Any, ...], mount: str, scope_ref: str, operations: frozenset[str]
) -> Any:
    matches = tuple(
        binding
        for binding in bindings
        if getattr(binding, "active", False) is True
        and getattr(binding, "mount", None) == mount
        and getattr(binding, "scope_ref", None) == scope_ref
    )
    if len(matches) != 1:
        raise ServiceExecutionSessionConfigError("RUNTIME_ROUTE_MISSING_OR_AMBIGUOUS")
    binding = matches[0]
    if getattr(binding, "required", None) is not True:
        raise ServiceExecutionSessionConfigError("RUNTIME_ROUTE_NOT_REQUIRED")
    granted = getattr(binding, "operations", None)
    if type(granted) not in (frozenset, set) or not operations <= granted:
        raise ServiceExecutionSessionConfigError("RUNTIME_ROUTE_OPERATION_MISSING")
    return binding


def _safe_code(error: BaseException, fallback: str) -> str:
    code = getattr(error, "code", None)
    if (
        type(code) is str
        and 0 < len(code) <= 64
        and code.isascii()
        and all(character.isalnum() or character in "_.-" for character in code)
    ):
        return code
    return fallback


def _safe_runtime_state(runtime: Any) -> Optional[str]:
    try:
        value = runtime.state
    except BaseException:
        return None
    if type(value) is str and value.isascii() and len(value) <= 64:
        return value
    return None


def _safe_nonnegative_int(value: Any) -> Optional[int]:
    if type(value) is int and value >= 0:
        return value
    return None


def _safe_runtime_metric(runtime: Any, name: str) -> Optional[int]:
    try:
        value = getattr(runtime, name, None)
    except BaseException:
        return None
    return _safe_nonnegative_int(value)
