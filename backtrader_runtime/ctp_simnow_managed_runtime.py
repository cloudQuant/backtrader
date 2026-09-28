"""Explicit, unregistered composition root for managed CTP SimNow execution.

The caller supplies every authority and every provider-facing dependency. This
module selects one exact configured MD/TD pair once, delegates client creation
to the artifact-first composition, and opens the journaled execution session
under its account lease and external writer fence. It has no CLI registration,
approval signer, key source, or default provider client.

Front selection proves bounded TCP reachability only. The injected native
client factory constructs one unstarted client for the exact pair it receives.
The readiness callback receives the port, exact selection, and that concrete
client as separate arguments. Managed readiness callbacks must accept the
market-client sink and failure-cleanup hook. They must hand off a fresh MD
client synchronously before starting it and must not retain the sink after the
callback returns. The owner seals that sink at callback return, then owns both
clients through startup, session use and shutdown. A failed login, query,
readiness check, or later uncertain write never triggers endpoint reselection.
"""

from __future__ import annotations

import inspect
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from . import ctp_simulation_execution as _execution
from .ctp_simnow_managed_composition import create_sealed_ctp_simnow_managed_port
from .ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    CtpSimNowManagedScopeSelection,
    select_ctp_simnow_managed_scope,
)
from .ctp_simulation_execution import (
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationExecutionSession,
    CtpSimulationSessionIdentity,
    CtpSimulationQueryEvidenceVerifier,
    CtpSimulationApprovalVerifier,
)
from .ctp_native_shutdown import stop_ctp_native_client
from .registry import EffectiveRuntimeConfig, RuntimeRegistry

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _reject(reason: str) -> None:
    raise CtpSimulationExecutionError(reason)


@dataclass(frozen=True)
class CtpSimNowManagedRuntime:
    """The one selected scope, optional TD proof, and leased execution session."""

    selection: CtpSimNowManagedScopeSelection
    session: CtpSimulationExecutionSession
    td_trading_readiness: Any = None

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "CtpSimNowManagedRuntime":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class _ManagedNativeResources:
    """Own native clients through readiness, execution open and final close.

    Stop is attempted at most once per client. A failed stop is remembered and
    re-raised on later close calls without retrying an uncertain native call.
    The raw trader is closed through its port once that port exists, preserving
    the port's cleanup contract; before that point the captured client is
    stopped directly.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._trader: Any = None
        self._extra_traders: list[Any] = []
        self._port: Any = None
        self._md_clients: list[Any] = []
        self._closed = False
        self._close_failed = False
        self._market_client_registration_sealed = False

    def set_trader(self, client: Any) -> None:
        with self._lock:
            if self._closed:
                _reject("managed_simnow_native_client_after_close")
            if self._trader is None:
                self._trader = client
                return
            if self._trader is not client and not any(
                existing is client for existing in self._extra_traders
            ):
                self._extra_traders.append(client)
                _reject("managed_simnow_native_client_count_mismatch")

    @property
    def market_client_count(self) -> int:
        with self._lock:
            return len(self._md_clients)

    def set_port(self, port: Any) -> None:
        with self._lock:
            if self._closed:
                _reject("managed_simnow_native_port_after_close")
            if self._port is not None and self._port is not port:
                _reject("managed_simnow_native_port_changed")
            self._port = port

    def register_market_client(self, client: Any) -> None:
        if client is None:
            _reject("managed_simnow_md_client_required")
        with self._lock:
            if client is self._trader or any(client is item for item in self._extra_traders):
                _reject("managed_simnow_md_client_aliases_td")
            if self._closed or self._market_client_registration_sealed:
                # The readiness adapter must hand off a fresh MD client before
                # starting it. A rejected late handoff never becomes owned and
                # must not be started by the callback.
                if not self._closed:
                    self._close_failed = True
                _reject("managed_simnow_md_client_registration_closed")
            if not any(existing is client for existing in self._md_clients):
                self._md_clients.append(client)
            if len(self._md_clients) > 1:
                self._close_failed = True
                _reject("managed_simnow_md_client_count_mismatch")
            try:
                fresh = (
                    getattr(client, "is_ready") is False
                    and type(getattr(client, "connection_generation")) is int
                    and getattr(client, "connection_generation") == 0
                    and getattr(client, "active_md_identity") is None
                )
            except BaseException:
                fresh = False
            if not fresh:
                # Keep a prematurely started client owned so cleanup can try
                # it, but do not let startup continue with untracked history.
                self._close_failed = True
                _reject("managed_simnow_md_client_must_be_fresh_at_handoff")

    def seal_market_client_registration(self) -> None:
        """Close the ownership sink when the synchronous readiness call ends."""
        with self._lock:
            self._market_client_registration_sealed = True
            if self._close_failed:
                _reject("managed_simnow_md_client_registration_failed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                if self._close_failed:
                    _reject("managed_simnow_native_close_failed")
                return
            self._closed = True
            failed = False
            # Stop MD before TD; attempt every owned client even if an earlier
            # stop fails. The account lease remains held by execution.open or
            # the live session until this entire method returns successfully.
            for client in self._md_clients:
                if not stop_ctp_native_client(client):
                    failed = True

            if self._port is not None:
                try:
                    close = getattr(self._port, "close", None)
                except BaseException:
                    close = None
                    failed = True
                if not callable(close):
                    failed = True
                else:
                    try:
                        close()
                    except BaseException:
                        failed = True
            for client in self._extra_traders:
                if not stop_ctp_native_client(client):
                    failed = True
            if self._port is None and self._trader is not None:
                if not stop_ctp_native_client(self._trader):
                    failed = True
            self._close_failed = self._close_failed or failed
            if self._close_failed:
                _reject("managed_simnow_native_close_failed")


class _OwnedNativePort:
    """Delegate the native protocol while extending its close ownership to MD."""

    def __init__(self, port: Any, resources: _ManagedNativeResources) -> None:
        self._port = port
        self._resources = resources

    def close(self) -> None:
        self._resources.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)


def _supports_readiness_lifecycle(callback: Callable[..., Any]) -> bool:
    """Whether an injected readiness adapter accepts the managed sink/hooks."""

    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    has_var_keyword = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    if has_var_keyword:
        return True
    return all(
        name in parameters
        and parameters[name].kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        for name in ("market_client_sink", "failure_cleanup")
    )


@dataclass(frozen=True)
class CtpSimNowNativeReadiness:
    """Exact pair/account evidence returned by a trusted startup adapter.

    The callback proves authenticated TD session identity and MD
    login/subscription/tick readiness through its supported adapter surface.
    These observations do not prove settlement confirmation, TD trading
    readiness, or order authority. The typed result binds the observations to
    the sealed config, account and exact selected pair; a plain boolean is
    insufficient.
    """

    config_digest: str
    registration_digest: str
    account_fingerprint_sha256: str
    md_front: str
    td_front: str
    td_ready: bool
    md_ready: bool

    @property
    def td_trading_ready(self) -> bool:
        """Native login evidence never claims settlement/write readiness."""

        return False

    @property
    def order_submission_authorized(self) -> bool:
        """Readiness observations never authorize an order submission."""

        return False

    def matches(self, selection: CtpSimNowManagedScopeSelection) -> bool:
        registration = selection.execution_registration
        return bool(
            self.config_digest == selection.config_digest
            and self.registration_digest == registration.digest
            and self.account_fingerprint_sha256 == registration.account_fingerprint_sha256
            and self.md_front == registration.md_front
            and self.td_front == registration.td_front
            and self.td_ready is True
            and self.md_ready is True
            and self.td_trading_ready is False
            and self.order_submission_authorized is False
        )


class _FailedNativePort:
    """Carry partial-client cleanup through execution.open's lease cleanup."""

    def __init__(
        self,
        reason: str,
        closer: Callable[[], None],
        pending_base_exception: Optional[BaseException] = None,
    ) -> None:
        self._reason = reason
        self._closer = closer
        self._pending_base_exception = pending_base_exception
        self._closed = False

    def get_execution_identity(self) -> CtpSimulationSessionIdentity:
        if self._pending_base_exception is not None:
            raise self._pending_base_exception
        _reject(self._reason)

    def close(self) -> None:
        if self._closed:
            return
        self._closer()
        self._closed = True

    def __getattr__(self, _name: str) -> Any:
        _reject(self._reason)


def _require_injected_authorities(
    *,
    execution_capability: object,
    runtime_admission_check: Callable[[], bool],
    runtime_order_binding: Callable[[str, bool], Mapping[str, Any]],
    runtime_credential_binding_factory: Callable[..., Any],
    approval_verifier: CtpSimulationApprovalVerifier,
    sdk_approval_rechecker: Callable[[Any, Mapping[str, Any]], bool],
    query_evidence_verifier: CtpSimulationQueryEvidenceVerifier,
    writer_fence: Any,
    native_client_factory: Callable[..., Any],
    native_readiness_check: Callable[..., CtpSimNowNativeReadiness],
) -> None:
    if execution_capability is None:
        _reject("explicit_managed_simnow_authorities_required")
    for callback in (
        runtime_admission_check,
        runtime_order_binding,
        runtime_credential_binding_factory,
        sdk_approval_rechecker,
        native_client_factory,
        native_readiness_check,
    ):
        if not callable(callback):
            _reject("explicit_managed_simnow_authorities_required")
    if not callable(getattr(approval_verifier, "verify", None)):
        _reject("approval_verifier_required")
    if not callable(getattr(query_evidence_verifier, "verify", None)):
        _reject("query_evidence_verifier_required")
    if (
        not callable(getattr(writer_fence, "assert_active", None))
        or type(getattr(writer_fence, "environment", None)) is not str
        or type(getattr(writer_fence, "account_fingerprint_sha256", None)) is not str
        or type(getattr(writer_fence, "fence_id", None)) is not str
    ):
        _reject("account_writer_fence_required")
    if writer_fence.environment != "simnow" or not _ID_RE.fullmatch(writer_fence.fence_id):
        _reject("account_writer_fence_scope_mismatch")
    try:
        writer_fence.assert_active()
    except Exception:
        _reject("account_writer_fence_unavailable")


def _identity_matches_selection(identity: Any, selection: CtpSimNowManagedScopeSelection) -> bool:
    registration = selection.execution_registration
    return bool(
        type(identity) is CtpSimulationSessionIdentity
        and identity.environment == registration.environment == "simnow"
        and identity.sdk_profile == registration.sdk_profile == "config_front_pair"
        and identity.td_front == registration.td_front
        and identity.md_front == registration.md_front
        and identity.account_fingerprint_sha256 == registration.account_fingerprint_sha256
        and identity.production is False
        and identity.native_gate_armed is False
        and identity.native_simnow_managed_mode is True
    )


def _td_config_from_artifact_first_port(
    port: Any,
    registration: CtpSimulationExecutionRegistration,
    config_type: type,
) -> Any:
    """Build the non-secret readiness identity from the post-gate port config."""

    try:
        config = getattr(port, "config")
        values = {
            "md_front": getattr(config, "md_front"),
            "td_front": getattr(config, "td_front"),
            "broker_id": getattr(config, "broker_id"),
            "user_id": getattr(config, "user_id"),
        }
    except Exception:
        _reject("managed_simnow_td_config_unavailable")
    if (
        values["md_front"] != registration.md_front
        or values["td_front"] != registration.td_front
        or type(values["broker_id"]) is not str
        or not values["broker_id"]
        or type(values["user_id"]) is not str
        or not values["user_id"]
    ):
        _reject("managed_simnow_td_config_scope_mismatch")
    try:
        return config_type(**values)
    except Exception:
        _reject("managed_simnow_td_config_invalid")


def _require_current_td_trading_readiness(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    native_readiness: CtpSimNowNativeReadiness,
    td_readiness: Any,
    config: Any,
    td_readiness_type: type,
) -> None:
    """Rebind the typed query result to the same live public TD session."""

    registration = selection.execution_registration
    if (
        type(td_readiness) is not td_readiness_type
        or td_readiness.config_digest != selection.config_digest
        or td_readiness.registration_digest != registration.digest
        or td_readiness.front_pair_set_sha256 != selection.front_pair_set_sha256
        or td_readiness.account_fingerprint_sha256 != registration.account_fingerprint_sha256
        or td_readiness.md_front != registration.md_front
        or td_readiness.td_front != registration.td_front
        or td_readiness.td_trading_ready is not True
        or td_readiness.md_ready is not True
        or td_readiness.settlement_proof_source != "confirmation_query"
        or td_readiness.settlement_readback_verified is not True
        or td_readiness.execution_gate_armed is not False
        or td_readiness.write_authority_granted is not False
        or type(td_readiness.connection_generation) is not int
        or td_readiness.connection_generation <= 0
        or type(td_readiness.trading_day) is not str
        or len(td_readiness.trading_day) != 8
        or not td_readiness.trading_day.isascii()
        or not td_readiness.trading_day.isdigit()
        or type(td_readiness.settlement_query_request_id) is not int
        or td_readiness.settlement_query_request_id <= 0
        or td_readiness.account_fingerprint_sha256 != native_readiness.account_fingerprint_sha256
        or config.md_front != registration.md_front
        or config.td_front != registration.td_front
    ):
        _reject("managed_simnow_td_trading_readiness_scope_mismatch")
    try:
        time.strptime(td_readiness.trading_day, "%Y%m%d")
    except (OverflowError, ValueError):
        _reject("managed_simnow_td_trading_readiness_scope_mismatch")
    try:
        state = trader_client.get_session_state()
        front = trader_client.get_front_binding_state()
        scope = trader_client.get_query_session_scope()
        counts = trader_client.get_request_counts()
    except Exception:
        _reject("managed_simnow_td_trading_readiness_state_unavailable")
    if type(state) is not dict or type(front) is not dict or type(counts) is not dict:
        _reject("managed_simnow_td_trading_readiness_state_unavailable")
    generation = td_readiness.connection_generation
    day = td_readiness.trading_day
    short_account = td_readiness.account_fingerprint
    if (
        type(short_account) is not str
        or len(short_account) != 16
        or any(character not in "0123456789abcdef" for character in short_account)
        or getattr(scope, "read_only_ready", None) is not True
        or type(getattr(scope, "connection_generation", None)) is not int
        or getattr(scope, "connection_generation", None) != generation
        or getattr(scope, "trading_day", None) != day
        or getattr(scope, "account_fingerprint", None) != short_account
        or getattr(scope, "broker_id", None) != config.broker_id
        or getattr(scope, "investor_id", None) != config.user_id
        or state.get("connected") is not True
        or state.get("read_only_ready") is not True
        or state.get("trading_ready") is not True
        or state.get("auto_settlement_confirm") is not False
        or type(state.get("connection_generation")) is not int
        or state.get("connection_generation") != generation
        or state.get("trading_day") != day
        or state.get("account_fingerprint") != short_account
        or state.get("settlement_state") != "confirmed"
        or state.get("settlement_readback_verified") is not True
        or state.get("settlement_proof_source") != "confirmation_query"
        or state.get("settlement_connection_generation") != generation
        or state.get("settlement_account_fingerprint") != short_account
        or state.get("settlement_trading_day") != day
        or state.get("settlement_proof_query_request_id")
        != td_readiness.settlement_query_request_id
        or state.get("execution_gate_armed") is not False
        or front.get("configured_front") != registration.td_front
        or front.get("registered_front") != registration.td_front
        or front.get("connection_confirmed_front") != registration.td_front
        or front.get("connected") is not True
        or front.get("native_api_current") is not True
        or front.get("bound_identity_current") is not True
        or type(front.get("connection_generation")) is not int
        or front.get("connection_generation") != generation
    ):
        _reject("managed_simnow_td_trading_readiness_session_changed")
    for name in ("settlement_confirm", "order_insert", "order_action"):
        if type(counts.get(name)) is not int or counts[name] != 0:
            _reject("managed_simnow_td_write_request_observed")
    if (
        type(counts.get("query_settlement_confirmation")) is not int
        or counts["query_settlement_confirmation"] != 1
    ):
        _reject("managed_simnow_td_settlement_query_count_mismatch")


def open_ctp_simnow_managed_runtime(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    policy: CtpSimNowManagedExecutionPolicy,
    *,
    execution_capability: object,
    runtime_admission_check: Callable[[], bool],
    runtime_order_binding: Callable[[str, bool], Mapping[str, Any]],
    runtime_credential_binding_factory: Callable[..., Any],
    approval_verifier: CtpSimulationApprovalVerifier,
    sdk_approval_rechecker: Callable[[Any, Mapping[str, Any]], bool],
    query_evidence_verifier: CtpSimulationQueryEvidenceVerifier,
    writer_fence: Any,
    native_client_factory: Callable[..., Any],
    native_readiness_check: Callable[..., CtpSimNowNativeReadiness],
    td_trading_readiness_check: Optional[Callable[..., Any]] = None,
    connector: Optional[Callable[[str, int, float], Any]] = None,
    process_factory: Optional[Callable[..., Any]] = None,
    clock: Optional[Callable[[], float]] = None,
    timeout_seconds: float = 3.0,
    repeated_samples: int = 3,
    order_field_factory: Optional[Callable[[], Any]] = None,
    action_field_factory: Optional[Callable[[], Any]] = None,
) -> CtpSimNowManagedRuntime:
    """Open one explicitly authorized SimNow session with one pinned front pair.

    The caller's factory must start the client from the exact sealed arguments
    it receives. No private client attribute is used as a start/connect seam.
    Static dependencies and the external writer fence are checked before the
    credential-free front probe. The selected scope is immutable and reused
    unchanged for artifact verification, client creation, readiness checking,
    and journal admission. Readiness failure closes the client and fails the
    open; it does not try another configured pair. An optional controlled TD
    trading-readiness callback runs after login/MD readiness and before
    ``execution.open``. When supplied, its typed result must remain bound to
    the same account, pair, generation, day, and settlement query. Omitting
    the callback preserves read-only startup; the SDK still rejects any later
    order write until its own current settlement readback is trading-ready.
    """

    if type(policy) is not CtpSimNowManagedExecutionPolicy:
        _reject("code_owned_policy_required")
    _require_injected_authorities(
        execution_capability=execution_capability,
        runtime_admission_check=runtime_admission_check,
        runtime_order_binding=runtime_order_binding,
        runtime_credential_binding_factory=runtime_credential_binding_factory,
        approval_verifier=approval_verifier,
        sdk_approval_rechecker=sdk_approval_rechecker,
        query_evidence_verifier=query_evidence_verifier,
        writer_fence=writer_fence,
        native_client_factory=native_client_factory,
        native_readiness_check=native_readiness_check,
    )
    if td_trading_readiness_check is not None and not callable(td_trading_readiness_check):
        _reject("managed_simnow_td_readiness_callback_invalid")

    try:
        selection = select_ctp_simnow_managed_scope(
            effective,
            registry,
            policy,
            connector=connector,
            process_factory=process_factory,
            clock=clock,
            timeout_seconds=timeout_seconds,
            repeated_samples=repeated_samples,
        )
    except CtpSimulationExecutionError:
        raise
    except Exception as exc:
        raise CtpSimulationExecutionError("managed_simnow_scope_selection_failed") from exc

    registration = selection.execution_registration
    if writer_fence.account_fingerprint_sha256 != registration.account_fingerprint_sha256:
        _reject("account_writer_fence_scope_mismatch")

    td_readiness_results: list[Any] = []

    def native_session_factory(
        requested_registration: CtpSimulationExecutionRegistration,
        lease: _execution.CtpAccountFlowLease,
    ) -> Any:
        if requested_registration is not registration:
            _reject("managed_simnow_selected_registration_changed")
        try:
            lease.assert_held(registration.account_fingerprint_sha256)
        except Exception:
            _reject("account_flow_lease_required")
        created_clients: list[Any] = []
        resources = _ManagedNativeResources()
        port: Any = None

        def tracked_client_factory(*args: Any, **kwargs: Any) -> Any:
            client = native_client_factory(*args, **kwargs)
            created_clients.append(client)
            resources.set_trader(client)
            return client

        def close_created_resource() -> None:
            resources.close()

        try:
            port = create_sealed_ctp_simnow_managed_port(
                effective,
                registry,
                registration,
                execution_capability=execution_capability,
                runtime_admission_check=runtime_admission_check,
                runtime_order_binding=runtime_order_binding,
                runtime_credential_binding_factory=runtime_credential_binding_factory,
                runtime_approval_verifier=approval_verifier,
                sdk_approval_rechecker=sdk_approval_rechecker,
                trader_client_factory=tracked_client_factory,
                order_field_factory=order_field_factory,
                action_field_factory=action_field_factory,
            )
            resources.set_port(port)
            if getattr(port, "registration", None) is not registration:
                raise CtpSimulationExecutionError("managed_simnow_port_registration_mismatch")
            if len(created_clients) != 1:
                raise CtpSimulationExecutionError("managed_simnow_native_client_count_mismatch")
            # The port intentionally does not expose its write-capable SDK
            # client. Pass the concrete client captured by the artifact-first
            # factory as an explicit, separately reviewed readiness input.
            if not _supports_readiness_lifecycle(native_readiness_check):
                resources.seal_market_client_registration()
                raise CtpSimulationExecutionError(
                    "managed_simnow_native_readiness_lifecycle_required"
                )
            try:
                readiness = native_readiness_check(
                    port,
                    selection,
                    created_clients[0],
                    market_client_sink=resources.register_market_client,
                    failure_cleanup=resources.close,
                )
            finally:
                resources.seal_market_client_registration()
            if resources.market_client_count != 1:
                raise CtpSimulationExecutionError("managed_simnow_md_client_ownership_missing")
            if type(readiness) is not CtpSimNowNativeReadiness or not readiness.matches(selection):
                raise CtpSimulationExecutionError("managed_simnow_native_readiness_rejected")
            if td_trading_readiness_check is not None:
                # Import after module initialization: the adapter's typed
                # inputs refer back to CtpSimNowNativeReadiness in this module.
                from .ctp_simnow_td_trading_readiness import (
                    CtpSimNowTdTradingReadiness,
                    CtpSimNowTdTradingReadinessConfig,
                )

                td_config = _td_config_from_artifact_first_port(
                    port,
                    registration,
                    CtpSimNowTdTradingReadinessConfig,
                )
                td_readiness = td_trading_readiness_check(
                    created_clients[0],
                    selection,
                    td_config,
                    native_readiness=readiness,
                    failure_cleanup=resources.close,
                )
                _require_current_td_trading_readiness(
                    created_clients[0],
                    selection,
                    readiness,
                    td_readiness,
                    td_config,
                    CtpSimNowTdTradingReadiness,
                )
                td_readiness_results.append(td_readiness)
            identity = port.get_execution_identity()
            if not _identity_matches_selection(identity, selection):
                raise CtpSimulationExecutionError("managed_simnow_native_identity_mismatch")
            return _OwnedNativePort(port, resources)
        except BaseException as exc:
            reason = (
                exc.reason
                if isinstance(exc, CtpSimulationExecutionError)
                else "managed_simnow_native_start_failed"
            )
            # Return a fail-closed adapter so open_ctp_simulation_execution
            # performs cleanup while it still owns the account lease. If close
            # fails, its standard path poisons the owner and retains the lease.
            failed = _FailedNativePort(
                str(reason),
                close_created_resource,
                None if isinstance(exc, Exception) else exc,
            )
            return failed

    try:
        session = _execution.open_ctp_simulation_execution(
            effective=effective,
            registry=registry,
            registration=registration,
            native_session_factory=native_session_factory,
            approval_verifier=approval_verifier,
            query_evidence_verifier=query_evidence_verifier,
            writer_fence=writer_fence,
        )
    except CtpSimulationExecutionError:
        raise
    except Exception as exc:
        raise CtpSimulationExecutionError("managed_simnow_execution_open_failed") from exc

    return CtpSimNowManagedRuntime(
        selection=selection,
        session=session,
        td_trading_readiness=(td_readiness_results[0] if td_readiness_results else None),
    )


__all__ = [
    "CtpSimNowManagedRuntime",
    "CtpSimNowNativeReadiness",
    "open_ctp_simnow_managed_runtime",
]
