"""Own one managed execution runtime for one Cerebro run.

The session is an explicit opt-in composition. Importing this module creates no
SDK runtime, transport, thread, or registration. The SDK assembly transfers
runtime ownership only after Backtrader preflight succeeds; a session consumes
that assembly on its first ``run`` attempt.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from bt_api_py.service_route_selection import ServiceStrategyAccountBookRoute

__all__ = [
    "ServiceExecutionSession",
    "ServiceExecutionSessionCleanupError",
    "ServiceExecutionSessionConfigError",
    "ServiceExecutionSessionError",
    "run_configured_cerebro",
]

_RUNTIME_OWNER_ATTRIBUTE = "_backtrader_service_execution_session_owner"
_REPORT_UNSET = object()


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
    """Bind an SDK execution assembly to one ``BtApiBroker`` and Cerebro run.

    The SDK assembly owns configured route validation and runtime lifecycle.
    This session binds its public execution client to Backtrader and controls
    the Cerebro/Broker/Store lifecycle on the assembly's owner thread.
    """

    def __init__(
        self,
        assembly: Any,
        *,
        refresh_interval_seconds: float = 1.0,
        max_refresh_interval_seconds: float = 30.0,
        backoff_factor: float = 2.0,
        limit: int = 32,
        monotonic_clock: Callable[[], float] = time.monotonic,
        strategy_account_book_routes: tuple[ServiceStrategyAccountBookRoute, ...] = (),
        strategy_group_routes: tuple[Any, ...] = (),
        recovery_callback: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        _validate_refresh_settings(
            refresh_interval_seconds,
            max_refresh_interval_seconds,
            backoff_factor,
            limit,
            monotonic_clock,
        )
        try:
            from bt_api_py.service_execution_assembly import ServiceExecutionAssembly
        except ImportError as error:
            raise ServiceExecutionSessionConfigError("SERVICE_SDK_UNAVAILABLE") from error

        if type(assembly) is not ServiceExecutionAssembly:
            raise ServiceExecutionSessionConfigError("INVALID_EXECUTION_ASSEMBLY")
        if assembly.state != "unclaimed":
            raise ServiceExecutionSessionConfigError("RUNTIME_OWNERSHIP_ALREADY_TRANSFERRED")

        runtime = assembly.runtime
        client = assembly.execution_client
        recovery_facade = assembly.recovery_facade
        recovery_flow = assembly.recovery_flow
        logical_run_id = assembly.logical_run_id
        recovery_event_version = assembly.recovery_event_version
        assembly_recovery_callback = assembly.recovery_callback
        routes = assembly.routes
        if (
            recovery_callback is not None
            and recovery_callback is not assembly_recovery_callback
        ):
            raise ServiceExecutionSessionConfigError("RECOVERY_CALLBACK_MISMATCH")
        recovery_callback = assembly_recovery_callback
        if recovery_callback is not None and recovery_facade is None:
            raise ServiceExecutionSessionConfigError("RECOVERY_CALLBACK_REQUIRES_FACADE")
        if recovery_callback is not None and not callable(recovery_callback):
            raise ServiceExecutionSessionConfigError("RECOVERY_CALLBACK_REQUIRES_FACADE")
        if recovery_callback is not None and recovery_event_version == 2:
            raise ServiceExecutionSessionConfigError(
                "RECOVERY_CALLBACK_USES_STRATEGY_NOTIFICATIONS"
            )
        from .service_execution_adapter import ServiceExecutionAdapter

        try:
            adapter = ServiceExecutionAdapter(
                client,
                recovery_flow=recovery_flow,
                require_recovery_baseline=(
                    recovery_flow is not None and recovery_event_version == 2
                ),
                recovery_event_version=recovery_event_version,
            )
        except Exception as error:
            code = _safe_code(error, "INVALID_EXECUTION_ROUTE")
            raise ServiceExecutionSessionConfigError(code) from None

        account_book_routes = _coerce_strategy_account_book_routes(
            runtime, strategy_account_book_routes, type(runtime)
        )
        group_routes = _coerce_strategy_group_routes(
            runtime, strategy_group_routes, type(runtime)
        )
        all_routes = account_book_routes + group_routes
        owned_runtimes = _unique_owned_runtimes(runtime, all_routes)

        group_adapter = None
        if group_routes:
            try:
                from bt_api_py.service_group_rpc_client import ServiceGroupRpcClient
                from .service_execution_group import (
                    ServiceExecutionGroupAdapter,
                )

                group_rpc_client = ServiceGroupRpcClient(group_routes)
                group_adapter = ServiceExecutionGroupAdapter(self, group_rpc_client)
            except Exception as error:
                code = _safe_code(error, "INVALID_GROUP_CONFIGURATION")
                raise ServiceExecutionSessionConfigError(code) from None

        self.assembly = assembly
        self.runtime = runtime
        self.client = client
        self.adapter = adapter
        self.mount = routes.writer_mount
        self.scope_ref = routes.writer_scope_ref
        self.query_mount = routes.query_mount
        self.query_scope_ref = routes.query_scope_ref
        self.recovery_facade = recovery_facade
        self.recovery_flow = recovery_flow
        self.logical_run_id = logical_run_id
        self.recovery_event_version = recovery_event_version
        self._recovery_consumer_token = uuid.uuid4().hex
        self._recovery_consumer_lease_acquired = False
        self.recovery_callback = recovery_callback
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
        self._strategy_group_route_specs = group_routes
        self._service_execution_group_adapter = group_adapter
        self._owned_runtimes = owned_runtimes
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
            try:
                self._claim_runtime_ownership()
            except BaseException as error:
                self._state = "rejected"
                self._record_report(
                    errors=(_safe_code(error, "RUNTIME_OWNERSHIP_FAILED"),),
                    store_connected=False,
                    runtime_close_attempted=False,
                )
                raise
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
            from .service_refresh_loop import ManagedOrderRefreshLoop

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
        try:
            self._claim_runtime_ownership()
        except BaseException as error:
            self._state = "rejected"
            self._record_report(
                errors=(_safe_code(error, "RUNTIME_OWNERSHIP_FAILED"),),
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
            if self._service_execution_group_adapter is not None:
                store.attach_service_execution_group_adapter(
                    self._service_execution_group_adapter
                )
            if self.recovery_flow is not None and self.recovery_event_version == 2:
                broker.configure_service_execution_recovery_feeds(tuple(cerebro.datas))
                self.adapter.configure_recovery_event_context_resolver(
                    broker.resolve_service_execution_recovery_event_context
                )
                if self.recovery_event_version == 2:
                    self.adapter.configure_recovery_intent_context_resolver(
                        broker.recovery_intent_context
                    )
            try:
                registration = self.assembly.start()
            except Exception as error:
                try:
                    from bt_api_py.service_execution_assembly import (
                        ServiceExecutionAssemblyError,
                    )
                except ImportError:
                    raise
                if type(error) is ServiceExecutionAssemblyError:
                    raise ServiceExecutionSessionConfigError(
                        _safe_code(error, "SERVICE_EXECUTION_START_FAILED")
                    ) from None
                raise
            self._writer_scope_identity = (
                registration.strategy_ref,
                registration.account_ref,
            )
            self._validate_strategy_account_book_routes()
            if self._service_execution_group_adapter is not None:
                self._service_execution_group_adapter.validate_registered_routes()
            if self.recovery_flow is not None:
                strategy_ref, account_ref = self._writer_scope_identity
                namespace = self.recovery_facade.create_namespace(
                    account_ref=account_ref,
                    strategy_ref=strategy_ref,
                    logical_run_id=self.logical_run_id,
                )
                self.adapter.bind_recovery_namespace(namespace)
                if self.recovery_event_version == 2:
                    self.adapter.acquire_recovery_consumer_lease(
                        self._recovery_consumer_token
                    )
                    self._recovery_consumer_lease_acquired = True
                    owner_book_view = self._account_book_route_views.get(
                        (strategy_ref, account_ref)
                    )
                    if owner_book_view is None:
                        raise ServiceExecutionSessionConfigError(
                            "RECOVERY_OWNER_BOOK_ROUTE_REQUIRED"
                        )
                    self.adapter.initialize_recovery(
                        owner_book_reader=owner_book_view.snapshot,
                    )
                else:
                    self.adapter.initialize_recovery()
            self._state = "running"
            result = cerebro.run(**run_kwargs)
        except BaseException as error:
            primary_error = error
        finally:
            if self._service_execution_group_adapter is not None:
                self._service_execution_group_adapter.deactivate()
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
            if self._recovery_consumer_lease_acquired:
                try:
                    self.adapter.release_recovery_consumer_lease(
                        self._recovery_consumer_token
                    )
                    self._recovery_consumer_lease_acquired = False
                except BaseException as error:
                    cleanup_errors.append("RECOVERY_CONSUMER_LEASE_RELEASE_FAILED")
                    if cleanup_exception is None:
                        cleanup_exception = error
            self._runtime_close_attempted = True
            # The SDK assembly closes every claimed owned runtime in reverse
            # acquisition order, even when startup stopped before reaching it.
            close_candidates = self._owned_runtimes
            try:
                self.assembly.close()
            except BaseException as error:
                if cleanup_exception is None:
                    cleanup_exception = error

            self._runtime_close_attempted = bool(self.assembly.close_attempted)
            runtime_facts = self.assembly.runtime_facts
            from bt_api_py.service_execution_assembly import summarize_runtime_facts

            runtime_summary = summarize_runtime_facts(runtime_facts, close_candidates)
            runtime_states = runtime_summary.states
            runtime_state = runtime_summary.primary_state
            unregister_uncertainties = runtime_summary.unregister_uncertainties
            cleanup_failures = runtime_summary.cleanup_failures
            if runtime_state == "close_failed":
                cleanup_errors.append("RUNTIME_CLOSE_FAILED")
            if any(
                state == "close_failed"
                for state in runtime_states[1:]
            ):
                cleanup_errors.append("ACCOUNT_BOOK_RUNTIME_CLOSE_FAILED")
            assembly_close_errors = self.assembly.close_errors
            if type(assembly_close_errors) is tuple:
                for code in assembly_close_errors:
                    if type(code) is str and code not in {
                        "UNREGISTER_UNCERTAIN",
                        "SERVICE_RUNTIME_CLOSE_FAILED",
                    }:
                        cleanup_errors.append(code)
            if cleanup_exception is not None and not any(
                state == "close_failed" for state in runtime_states
            ) and not assembly_close_errors:
                cleanup_errors.append("RUNTIME_CLOSE_FAILED")
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
                runtime_close_attempted=self._runtime_close_attempted,
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
        self.assembly.maintain()
        if self.recovery_flow is not None:
            if self.recovery_event_version == 2:
                self.adapter.renew_recovery_consumer_lease(self._recovery_consumer_token)
            return self.adapter.refresh_recovery_events(
                callback=(self.recovery_callback if self.recovery_event_version == 1 else None),
            )
        return self._refresh_loop.run_once()

    def broker_starting(self, broker: Any) -> None:
        """Fence direct Broker.start calls to the active owning session."""

        self._assert_creator_thread()
        if (
            broker is not self._broker
            or self._state != "running"
            or self._broker_stop_attempted
            or self.assembly.state != "registered"
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
        if self.assembly.state != "unclaimed":
            raise ServiceExecutionSessionConfigError("RUNTIME_OWNERSHIP_ALREADY_TRANSFERRED")
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
            or bool(store.service_execution_group_active)
            or getattr(store, "_cerebro_managed_lifecycle", True) is False
            or getattr(broker, "_service_execution_session", None) is not None
        ):
            raise ServiceExecutionSessionConfigError("BROKER_OR_STORE_ALREADY_ACTIVE")
        if not callable(getattr(broker, "attach_service_execution_session", None)):
            raise ServiceExecutionSessionConfigError("BROKER_SESSION_HOOK_UNAVAILABLE")
        return broker, store

    def _validate_strategy_account_book_routes(self) -> None:
        from bt_api_py.service_route_selection import resolve_strategy_account_book_routes

        from .service_strategy_account_book import (
            ServiceStrategyAccountBookView,
        )

        resolved = resolve_strategy_account_book_routes(
            self.runtime, self.query_mount, self.query_scope_ref,
            self._account_book_route_specs, error_type=ServiceExecutionSessionConfigError,
        )

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
        """Release the SDK assembly fence before any runtime start attempt."""

        if self.assembly.state == "unclaimed":
            return ()
        try:
            return self.assembly.release_unstarted()
        except BaseException as error:
            return (_safe_code(error, "RUNTIME_OWNER_RELEASE_FAILED"),)

    def _claim_runtime_ownership(self) -> None:
        """Transfer every BT-selected owned runtime to the SDK assembly."""

        try:
            self.assembly.claim_owned_runtimes(
                additional_owned_runtimes=self._owned_runtimes[1:]
            )
        except BaseException as error:
            raise ServiceExecutionSessionConfigError(
                _safe_code(error, "RUNTIME_OWNERSHIP_FAILED")
            ) from None


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
        from bt_api_py.service_execution_assembly import (
            ServiceExecutionAssemblyError,
            assemble_service_execution,
        )
    except ImportError as error:
        raise ServiceExecutionSessionConfigError("SERVICE_SDK_UNAVAILABLE") from error

    options = {} if session_options is None else session_options
    supported_options = {
        "refresh_interval_seconds",
        "max_refresh_interval_seconds",
        "backoff_factor",
        "limit",
        "monotonic_clock",
        "recovery_event_version",
    }
    recovery_event_version = (
        options.get("recovery_event_version", 1) if type(options) is dict else 1
    )
    session_options_after_validation: list[dict[str, Any]] = []
    factory_error: list[BaseException] = []
    factory_callable = runtime_factory if callable(runtime_factory) else None

    if factory_callable is None:
        assembly_factory = runtime_factory
    else:
        def call_runtime_factory(parsed: Any) -> Any:
            if type(options) is not dict:
                raise ServiceExecutionSessionConfigError("INVALID_SESSION_OPTIONS")
            if set(options) - supported_options:
                raise ServiceExecutionSessionConfigError("UNSUPPORTED_SESSION_OPTION")
            assembly_options = dict(options)
            assembly_options.pop("recovery_event_version", None)
            session_options_after_validation.append(assembly_options)
            try:
                return factory_callable(parsed)
            except BaseException as error:
                factory_error.append(error)
                raise

        assembly_factory = call_runtime_factory

    try:
        assembly = assemble_service_execution(
            client_config,
            runtime_factory=assembly_factory,
            recovery_event_version=recovery_event_version,
        )
    except ServiceExecutionAssemblyError as error:
        if factory_error and error is factory_error[0]:
            raise
        raise ServiceExecutionSessionConfigError(
            _safe_code(error, "SERVICE_ASSEMBLY_FAILED")
        ) from None

    if not session_options_after_validation:
        raise ServiceExecutionSessionError("SESSION_OPTIONS_NOT_VALIDATED")
    session = ServiceExecutionSession(
        assembly,
        **session_options_after_validation[0],
    )
    return session.run(cerebro, **run_kwargs)


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
    primary_runtime: Any, routes: tuple[Any, ...], runtime_type: type,
) -> tuple[Any, ...]:
    from bt_api_py.service_route_selection import coerce_strategy_account_book_routes
    return coerce_strategy_account_book_routes(
        primary_runtime, routes, runtime_type,
        error_type=ServiceExecutionSessionConfigError,
        runtime_has_external_owner=lambda runtime: hasattr(runtime, _RUNTIME_OWNER_ATTRIBUTE),
    )


def _unique_owned_runtimes(primary_runtime: Any, routes: tuple[Any, ...]) -> tuple[Any, ...]:
    from bt_api_py.service_route_selection import unique_owned_runtimes
    return unique_owned_runtimes(primary_runtime, routes, error_type=ServiceExecutionSessionConfigError)


def _coerce_strategy_group_routes(
    primary_runtime: Any,
    routes: tuple[Any, ...],
    runtime_type: type,
) -> tuple[Any, ...]:
    from bt_api_py.service_route_selection import coerce_strategy_group_routes
    return coerce_strategy_group_routes(
        primary_runtime, routes, runtime_type,
        error_type=ServiceExecutionSessionConfigError,
        runtime_has_external_owner=lambda runtime: hasattr(runtime, _RUNTIME_OWNER_ATTRIBUTE),
    )


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


def _safe_code(error: BaseException, fallback: str) -> str:
    from bt_api_py.service_execution_assembly import safe_service_execution_error_code

    return safe_service_execution_error_code(error, fallback)


def _safe_runtime_state(runtime: Any) -> Optional[str]:
    from bt_api_py.service_execution_assembly import safe_runtime_state

    return safe_runtime_state(runtime)


def _safe_runtime_metric(runtime: Any, name: str) -> Optional[int]:
    from bt_api_py.service_execution_assembly import safe_runtime_metric

    return safe_runtime_metric(runtime, name)
