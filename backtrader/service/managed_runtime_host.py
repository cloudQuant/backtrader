"""Run one Cerebro instance under an explicitly supplied SDK runtime.

This module is a thin lifecycle bridge. It does not create provider clients,
derive identities, or grant write authority. The SDK composition owns those
decisions and the provider's thread-sensitive runtime. A session binds the
composition to the exact API object held by one BtApiStore, pumps it from the
Broker's normal Cerebro thread, and closes it once after Cerebro cleanup.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Tuple

__all__ = (
    "ManagedRuntimeCerebroCleanupError",
    "ManagedRuntimeCerebroCleanupReport",
    "ManagedRuntimeCerebroError",
    "ManagedRuntimeCerebroSession",
)


class ManagedRuntimeCerebroError(RuntimeError):
    """Finite Backtrader-side lifecycle error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ManagedRuntimeCerebroCleanupError(ManagedRuntimeCerebroError):
    """Cerebro or SDK cleanup could not be confirmed."""

    def __init__(self, code: str, report: "ManagedRuntimeCerebroCleanupReport") -> None:
        self.report = report
        super().__init__(code)


@dataclass(frozen=True)
class ManagedRuntimeCerebroCleanupReport:
    """Finite lifecycle facts for one consumed composition."""

    state: str
    errors: Tuple[str, ...]
    broker_start_attempted: bool
    broker_stop_attempted: bool
    broker_stop_confirmed: Optional[bool]
    store_connected: Optional[bool]
    composition_close_attempted: bool
    composition_close_confirmed: Optional[bool]


class ManagedRuntimeCerebroSession:
    """Bind one SDK composition to one Broker/Cerebro run on one thread.

    The caller must construct the SDK composition, this session, its Store, and
    its Broker on the same thread. ``run`` rechecks that the current thread is
    still the session's owner. The provider remains responsible for validating
    its own runtime binding and owner thread inside ``serve_once`` and
    ``close``. A composition's API object is checked by identity against the
    Store's ``sdk_api``; this proves routing consistency only, not readiness or
    authorization.

    Passing a composition transfers its one-shot close lifecycle to this
    session. ``run`` always attempts one close, including when preflight,
    Broker startup, strategy execution, or Broker shutdown raises. A close
    failure is reported as cleanup uncertainty and is never retried.
    """

    def __init__(self, composition: Any) -> None:
        try:
            from bt_api_py.managed_runtime_composition import ManagedRuntimeComposition
        except Exception:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SDK_UNAVAILABLE") from None

        if type(composition) is not ManagedRuntimeComposition:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_COMPOSITION_INVALID")
        try:
            api = composition.api
            serve_once = composition.serve_once
            close = composition.close
        except Exception:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_COMPOSITION_INVALID") from None
        if api is None or not callable(serve_once) or not callable(close):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_COMPOSITION_INVALID")

        self.composition = composition
        self._api = api
        self._serve_once = serve_once
        self._close = close
        self._owner_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._state = "new"
        self._run_attempted = False
        self._run_active = False
        self._close_attempted = False
        self._close_confirmed = None
        self._close_error = None
        self._owner_thread_verified = False
        self._owner_thread_verification_failed = False
        self._owner_thread_verification_error_code = None
        self._close_prohibited = False
        self._serve_failed = False
        self._broker = None
        self._store = None
        self._broker_start_attempted = False
        self._broker_binding_failed = False
        self._broker_stop_attempted = False
        self._broker_stop_confirmed = None
        self._broker_stop_failed = False
        self._broker_stop_repeated = False
        self._cleanup_report = self._make_report("new", ())

    @property
    def state(self) -> str:
        return self._state

    @property
    def cleanup_report(self) -> ManagedRuntimeCerebroCleanupReport:
        return self._cleanup_report

    @property
    def run_attempted(self) -> bool:
        return self._run_attempted

    def bind_broker(self, broker: Any) -> None:
        """Bind only the exact Broker whose Store holds this composition API."""

        self._assert_owner_thread()
        with self._lock:
            if self._state != "binding" or self._broker is not None:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_BINDING_INVALID")
            store = getattr(broker, "store", None)
            try:
                store_api = getattr(store, "sdk_api", None)
            except Exception:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_STORE_API_UNAVAILABLE") from None
            if store_api is not self._api:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_STORE_API_MISMATCH")
            self._broker = broker
            self._store = store
            self._state = "bound"

    def assert_owner_thread(self) -> None:
        """Verify this caller and the SDK composition's actual thread contract."""

        self._assert_owner_thread()
        self._verify_composition_owner_thread()

    def broker_starting(self, broker: Any) -> None:
        """Record the one Broker startup attempt on the owner thread."""

        self.assert_owner_thread()
        with self._lock:
            if broker is not self._broker or self._state != "bound":
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_NOT_BOUND")
            if self._broker_start_attempted:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_START_REPEATED")
            self._broker_start_attempted = True
            self._state = "running"

    def poll(self, broker: Any) -> None:
        """Pump one SDK maintenance step from Broker.next, without retries."""

        self.assert_owner_thread()
        with self._lock:
            if (
                broker is not self._broker
                or not self._broker_start_attempted
                or self._broker_stop_attempted
                or self._close_attempted
            ):
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SESSION_NOT_RUNNING")
            if self._serve_failed:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SERVE_AFTER_FAILURE")
        try:
            result = self._serve_once()
            if result is not None:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SERVE_RESULT_INVALID")
        except BaseException:
            with self._lock:
                self._serve_failed = True
                self._state = "serve_failed"
            raise

    def broker_stopping(self, broker: Any) -> None:
        """Record a Broker stop attempt without taking over Broker cleanup."""

        self.assert_owner_thread()
        with self._lock:
            if broker is not self._broker:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_NOT_BOUND")
            if self._broker_stop_attempted:
                self._broker_stop_repeated = True
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_STOP_REPEATED")
            self._broker_stop_attempted = True
            self._state = "stopping"

    def broker_stop_failed(self, broker: Any, error: BaseException) -> None:
        """Latch a failed Broker stop; do not mask its original exception."""

        if broker is not self._broker:
            return
        with self._lock:
            self._broker_stop_failed = True

    def broker_binding_failed(self, broker: Any, error: BaseException) -> None:
        """Latch Store ownership-transfer failure before Broker startup."""

        if broker is not self._broker:
            return
        with self._lock:
            self._broker_binding_failed = True

    def broker_stopped(self, broker: Any, result: Any) -> None:
        """Record a positive shutdown result only when Broker reports PASS."""

        if broker is not self._broker:
            return
        with self._lock:
            if self._broker_stop_confirmed is not None:
                self._broker_stop_repeated = True
                return
            self._broker_stop_confirmed = bool(
                isinstance(result, Mapping) and result.get("status") == "PASS"
            )

    def run(self, cerebro: Any, **run_kwargs: Any) -> Any:
        """Run one ordinary Cerebro session and consume composition ownership."""

        self._assert_owner_thread()
        with self._lock:
            if self._run_attempted:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SESSION_ALREADY_USED")
            if self._close_attempted:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SESSION_ALREADY_CLOSED")
            self._run_attempted = True
            self._run_active = True
            self._state = "preflight"

        result = None
        primary_error = None
        try:
            broker, store = self._preflight(cerebro, run_kwargs)
            if not cerebro.datas and run_kwargs.get("channel") is None:
                result = cerebro.run(**run_kwargs)
            else:
                with self._lock:
                    self._state = "binding"
                broker.attach_managed_runtime_session(self)
                if self._broker is not broker or self._store is not store:
                    raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_BINDING_INVALID")
                result = cerebro.run(**run_kwargs)
        except BaseException as error:
            primary_error = error

        cleanup_errors = self._collect_cleanup_errors()
        if self._owner_thread_verification_failed:
            cleanup_errors.append(
                self._owner_thread_verification_error_code
                or "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
            self._close_prohibited = True
            close_error = None
        elif cleanup_errors:
            # Store/Broker work may still own the route. Do not close the SDK
            # composition while shutdown is incomplete or uncertain.
            cleanup_errors.append("COMPOSITION_CLOSE_SKIPPED_SHUTDOWN_UNCONFIRMED")
            self._close_prohibited = True
            close_error = None
        else:
            close_error = self._close_once()
            if close_error is not None:
                cleanup_errors.append(
                    _safe_error_code(close_error, "MANAGED_RUNTIME_CLOSE_FAILED")
                )
        with self._lock:
            self._run_active = False
            if cleanup_errors:
                self._state = "cleanup_uncertain"
            else:
                self._state = "closed"
            self._cleanup_report = self._make_report(self._state, tuple(cleanup_errors))
            report = self._cleanup_report

        if cleanup_errors:
            error = ManagedRuntimeCerebroCleanupError(
                "MANAGED_RUNTIME_CLEANUP_UNCERTAIN", report
            )
            if primary_error is not None:
                raise error from primary_error
            if close_error is not None:
                raise error from close_error
            raise error
        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__)
        return result

    def close(self) -> ManagedRuntimeCerebroCleanupReport:
        """Close an unused session once, or report its prior close result."""

        self._assert_owner_thread()
        with self._lock:
            if self._run_active:
                raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_CLOSE_BUSY")
            if self._close_prohibited:
                report = self._cleanup_report
                raise ManagedRuntimeCerebroCleanupError(
                    "MANAGED_RUNTIME_CLEANUP_UNCERTAIN", report
                )
            if self._close_attempted:
                report = self._cleanup_report
                close_error = self._close_error
                if close_error is not None:
                    raise ManagedRuntimeCerebroCleanupError(
                        "MANAGED_RUNTIME_CLOSE_UNCERTAIN", report
                    ) from close_error
                return report
        if not self._owner_thread_verified:
            try:
                self._verify_composition_owner_thread()
            except ManagedRuntimeCerebroError:
                self._close_prohibited = True
                with self._lock:
                    self._state = "cleanup_uncertain"
                    self._cleanup_report = self._make_report(
                        self._state,
                        (
                            self._owner_thread_verification_error_code
                            or "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED",
                        ),
                    )
                    report = self._cleanup_report
                raise ManagedRuntimeCerebroCleanupError(
                    "MANAGED_RUNTIME_CLEANUP_UNCERTAIN", report
                ) from None
        close_error = self._close_once()
        errors = []
        if close_error is not None:
            errors.append(_safe_error_code(close_error, "MANAGED_RUNTIME_CLOSE_FAILED"))
        with self._lock:
            state = "cleanup_uncertain" if errors else "closed"
            self._state = state
            self._cleanup_report = self._make_report(state, tuple(errors))
            report = self._cleanup_report
        if errors:
            error = ManagedRuntimeCerebroCleanupError(
                "MANAGED_RUNTIME_CLOSE_UNCERTAIN", report
            )
            raise error from close_error
        return report

    def _preflight(self, cerebro: Any, run_kwargs: dict) -> Tuple[Any, Any]:
        self.assert_owner_thread()
        if "channel" in run_kwargs and run_kwargs["channel"] is not None:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_CHANNEL_MODE_UNSUPPORTED")
        if bool(getattr(cerebro, "_dooptimize", False)):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_OPTIMIZATION_UNSUPPORTED")

        try:
            from backtrader.brokers.btapibroker import BtApiBroker
            from backtrader.cerebro import Cerebro
            from backtrader.stores.btapistore import BtApiStore
        except Exception:
            raise ManagedRuntimeCerebroError(
                "MANAGED_RUNTIME_BACKTRADER_TYPES_UNAVAILABLE"
            ) from None

        if not isinstance(cerebro, Cerebro):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_CEREBRO_INVALID")
        broker = cerebro.getbroker()
        if not isinstance(broker, BtApiBroker) or getattr(cerebro, "_broker", None) is not broker:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_INVALID")
        store = getattr(broker, "store", None)
        if not isinstance(store, BtApiStore):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_STORE_INVALID")
        if getattr(cerebro, "signals", None):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_SIGNALS_UNSUPPORTED")
        if len(getattr(cerebro, "strats", ())) > 1:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_MULTIPLE_STRATEGY_RUNS_UNSUPPORTED")
        if (
            bool(getattr(broker, "_live_started", False))
            or bool(getattr(broker, "_startup_ready", False))
            or bool(getattr(store, "_started", False))
            or store.is_connected is not False
            or bool(getattr(store, "managed_execution_active", False))
            or getattr(store, "_cerebro_managed_lifecycle", True) is False
            or getattr(broker, "_service_execution_session", None) is not None
            or getattr(broker, "_managed_runtime_session", None) is not None
        ):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_OR_STORE_ALREADY_ACTIVE")
        if getattr(store, "sdk_api", None) is not self._api:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_STORE_API_MISMATCH")
        if not callable(getattr(broker, "attach_managed_runtime_session", None)):
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_BROKER_HOOK_UNAVAILABLE")
        return broker, store

    def _collect_cleanup_errors(self) -> list:
        errors = []
        with self._lock:
            started = self._broker_start_attempted
            stop_attempted = self._broker_stop_attempted
            stop_confirmed = self._broker_stop_confirmed
            stop_failed = self._broker_stop_failed
            binding_failed = self._broker_binding_failed
            stop_repeated = self._broker_stop_repeated
            store = self._store
        if binding_failed:
            errors.append("BROKER_STORE_BINDING_FAILED")
        if started:
            if not stop_attempted:
                errors.append("BROKER_STOP_NOT_ATTEMPTED")
            if stop_failed:
                errors.append("BROKER_STOP_FAILED")
            if stop_repeated:
                errors.append("BROKER_STOP_REPEATED")
            if stop_confirmed is not True:
                errors.append("BROKER_STOP_NOT_CONFIRMED")
        if store is None:
            return errors
        try:
            connected = getattr(store, "is_connected", None)
        except BaseException:
            connected = None
        if connected is not False:
            errors.append("STORE_SHUTDOWN_NOT_CONFIRMED")
        return list(dict.fromkeys(errors))

    def _close_once(self) -> Optional[BaseException]:
        if self._close_prohibited or not self._owner_thread_verified:
            return ManagedRuntimeCerebroError(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        with self._lock:
            if self._close_attempted:
                return self._close_error
            self._close_attempted = True
            self._state = "closing"
        try:
            self._close()
        except BaseException as error:
            with self._lock:
                self._close_error = error
                self._close_confirmed = False
                self._state = "close_failed"
            return error
        with self._lock:
            self._close_confirmed = True
        return None

    def _make_report(
        self,
        state: str,
        errors: Tuple[str, ...],
    ) -> ManagedRuntimeCerebroCleanupReport:
        try:
            store_connected = (
                getattr(self._store, "is_connected", None) if self._store is not None else None
            )
        except BaseException:
            store_connected = None
        return ManagedRuntimeCerebroCleanupReport(
            state=state,
            errors=errors,
            broker_start_attempted=self._broker_start_attempted,
            broker_stop_attempted=self._broker_stop_attempted,
            broker_stop_confirmed=self._broker_stop_confirmed,
            store_connected=store_connected,
            composition_close_attempted=self._close_attempted,
            composition_close_confirmed=self._close_confirmed,
        )

    def _assert_owner_thread(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise ManagedRuntimeCerebroError("MANAGED_RUNTIME_WRONG_THREAD")

    def _verify_composition_owner_thread(self) -> None:
        if self._owner_thread_verification_failed:
            raise ManagedRuntimeCerebroError(
                self._owner_thread_verification_error_code
                or "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        try:
            verifier = getattr(self.composition, "assert_owner_thread", None)
        except BaseException:
            verifier = None
        if not callable(verifier):
            self._latch_owner_thread_failure(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        try:
            result = verifier()
        except BaseException as error:
            self._latch_owner_thread_failure(_owner_thread_error_code(error))
        if result is not None:
            self._latch_owner_thread_failure(
                "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
            )
        self._owner_thread_verified = True

    def _latch_owner_thread_failure(self, code: str) -> None:
        self._owner_thread_verification_failed = True
        self._owner_thread_verification_error_code = code
        self._close_prohibited = True
        raise ManagedRuntimeCerebroError(code) from None


def _safe_error_code(error: BaseException, fallback: str) -> str:
    try:
        code = getattr(error, "code", None)
    except BaseException:
        return fallback
    if (
        type(code) is str
        and code
        and len(code) <= 96
        and all(
            character.isascii() and (character.isalnum() or character == "_")
            for character in code
        )
    ):
        return code
    return fallback


def _owner_thread_error_code(error: BaseException) -> str:
    allowed = {
        "MANAGED_RUNTIME_THREAD_CONSTRAINT_INVALID",
        "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED",
        "MANAGED_RUNTIME_WRONG_THREAD",
        "MANAGED_RUNTIME_CLOSE_ALREADY_ATTEMPTED",
        "MANAGED_RUNTIME_SERVE_BUSY",
    }
    try:
        code = getattr(error, "code", None)
    except BaseException:
        code = None
    if type(code) is str and code in allowed:
        return code
    return "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
