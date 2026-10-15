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
from dataclasses import dataclass
from typing import Any, Callable, Optional

__all__ = [
    "ServiceExecutionSession",
    "ServiceExecutionSessionCleanupError",
    "ServiceExecutionSessionConfigError",
    "ServiceExecutionSessionError",
]

_RUNTIME_OWNER_ATTRIBUTE = "_backtrader_service_execution_session_owner"
_RUNTIME_OWNER_LOCK = threading.Lock()
_WRITER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
_QUERY_OPERATIONS = frozenset({"orders.query"})


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
        with _RUNTIME_OWNER_LOCK:
            if runtime.state != "new":
                raise ServiceExecutionSessionConfigError("RUNTIME_NOT_NEW")
            if hasattr(runtime, _RUNTIME_OWNER_ATTRIBUTE):
                raise ServiceExecutionSessionConfigError("RUNTIME_ALREADY_OWNED")
            try:
                setattr(runtime, _RUNTIME_OWNER_ATTRIBUTE, self)
            except Exception:
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
            self._state = "rejected"
            self._record_report(
                errors=("PREFLIGHT_REJECTED",),
                store_connected=None,
                runtime_close_attempted=False,
            )
            raise

        # Cerebro's documented no-data behavior is an empty result. Consume the
        # session but do not attach it or start/close a runtime with no work.
        if not cerebro.datas and run_kwargs.get("channel") is None:
            self._state = "closed_unstarted"
            self._record_report(
                errors=(),
                store_connected=False,
                runtime_close_attempted=False,
            )
            return []

        from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop

        try:
            refresh_loop = ManagedOrderRefreshLoop(
                broker,
                interval_seconds=self._refresh_interval_seconds,
                max_interval_seconds=self._max_refresh_interval_seconds,
                backoff_factor=self._backoff_factor,
                limit=self._limit,
                monotonic_clock=self._monotonic_clock,
            )
        except BaseException:
            self._state = "rejected"
            self._record_report(
                errors=("REFRESH_LOOP_SETUP_FAILED",),
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
            self.runtime.start()
            self._validate_registered_routes()
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
            try:
                self.runtime.close()
            except BaseException as error:
                cleanup_errors.append(_safe_code(error, "RUNTIME_CLOSE_FAILED"))
                if cleanup_exception is None:
                    cleanup_exception = error

            runtime_state = _safe_runtime_state(self.runtime)
            unregister_uncertainties = _safe_runtime_metric(
                self.runtime, "unregister_uncertainties"
            )
            cleanup_failures = _safe_runtime_metric(self.runtime, "cleanup_failures")
            if runtime_state == "close_failed":
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
        self.runtime.maintain()
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

    def _record_report(
        self,
        *,
        errors: tuple[str, ...],
        store_connected: Optional[bool],
        runtime_state: Optional[str] = None,
        unregister_uncertainties: Optional[int] = None,
        cleanup_failures: Optional[int] = None,
        runtime_close_attempted: bool,
    ) -> None:
        if runtime_state is None:
            runtime_state = _safe_runtime_state(self.runtime)
        if unregister_uncertainties is None:
            unregister_uncertainties = _safe_runtime_metric(
                self.runtime, "unregister_uncertainties"
            )
        if cleanup_failures is None:
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
