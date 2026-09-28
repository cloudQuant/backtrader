"""One config-selected composition root for future managed CTP sessions.

The shared root delegates sandbox sessions to the existing SimNow runtime,
which owns its typed risk, approval, writer-fence, lease, native-client,
OrderRef and action-journal path. Live mode enters a separate typed adapter,
but that adapter currently fails closed because production has no accepted
native session, writer fence, or durable action-journal owner. This module is
unregistered and does not create provider dependencies of its own.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .ctp_mode_scope import CtpModeScopeBinding, bind_ctp_mode_scope
from .ctp_production_execution_admission import (
    CtpProductionExecutionRegistration,
    _require_registration_seal as _require_production_registration_seal,
)
from .ctp_shared_managed_runner import (
    CtpSharedManagedRunnerError,
    _require_current_effective_runtime_config,
    _require_shared_runner_contract,
)
from .ctp_simnow_managed_operator import CtpSimNowManagedExecutionPolicy
from .ctp_simnow_managed_runtime import (
    CtpSimNowManagedRuntime,
    open_ctp_simnow_managed_runtime,
)
from .ctp_simulation_execution import (
    CtpSimulationExecutionRegistration,
    _execution_journal_scope,
)
from .registry import EffectiveRuntimeConfig, RuntimeRegistry


_SIMULATION = ("simulation", "sandbox")
_PRODUCTION = ("live", "managed_live_direct")
_SESSION_DOMAIN = b"backtrader-shared-managed-ctp-session-v1\0"


class CtpSharedManagedRuntimeError(ValueError):
    """Redacted rejection from the config-selected shared CTP runtime."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpSharedManagedRuntimeError(reason) from None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


@dataclass(frozen=True, repr=False)
class CtpSimNowManagedSessionDependencies:
    """Explicit authorities and factories required by the existing SimNow opener."""

    execution_capability: object = field(repr=False)
    runtime_admission_check: Callable[[], bool] = field(repr=False)
    runtime_order_binding: Callable[[str, bool], Any] = field(repr=False)
    runtime_credential_binding_factory: Callable[..., Any] = field(repr=False)
    approval_verifier: Any = field(repr=False)
    sdk_approval_rechecker: Callable[[Any, Any], bool] = field(repr=False)
    query_evidence_verifier: Any = field(repr=False)
    writer_fence: Any = field(repr=False)
    native_client_factory: Callable[..., Any] = field(repr=False)
    native_readiness_check: Callable[..., Any] = field(repr=False)
    td_trading_readiness_check: Optional[Callable[..., Any]] = field(default=None, repr=False)
    connector: Optional[Callable[[str, int, float], Any]] = field(default=None, repr=False)
    process_factory: Optional[Callable[..., Any]] = field(default=None, repr=False)
    clock: Optional[Callable[[], float]] = field(default=None, repr=False)
    timeout_seconds: float = 3.0
    repeated_samples: int = 3
    order_field_factory: Optional[Callable[[], Any]] = field(default=None, repr=False)
    action_field_factory: Optional[Callable[[], Any]] = field(default=None, repr=False)


@dataclass(frozen=True, repr=False)
class CtpSimNowManagedSessionAdapter:
    """Typed bridge to the existing SimNow lifecycle and durable execution path."""

    policy: CtpSimNowManagedExecutionPolicy = field(repr=False)
    dependencies: CtpSimNowManagedSessionDependencies = field(repr=False)

    def open_session(
        self, effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
    ) -> CtpSimNowManagedRuntime:
        if type(self.policy) is not CtpSimNowManagedExecutionPolicy:
            _reject("simnow_session_policy_required")
        if type(self.dependencies) is not CtpSimNowManagedSessionDependencies:
            _reject("simnow_session_dependencies_required")
        if self.policy.runtime_registration is not effective.registration:
            _reject("simnow_session_registration_mismatch")
        dependencies = self.dependencies
        try:
            return open_ctp_simnow_managed_runtime(
                effective,
                registry,
                self.policy,
                execution_capability=dependencies.execution_capability,
                runtime_admission_check=dependencies.runtime_admission_check,
                runtime_order_binding=dependencies.runtime_order_binding,
                runtime_credential_binding_factory=dependencies.runtime_credential_binding_factory,
                approval_verifier=dependencies.approval_verifier,
                sdk_approval_rechecker=dependencies.sdk_approval_rechecker,
                query_evidence_verifier=dependencies.query_evidence_verifier,
                writer_fence=dependencies.writer_fence,
                native_client_factory=dependencies.native_client_factory,
                native_readiness_check=dependencies.native_readiness_check,
                td_trading_readiness_check=dependencies.td_trading_readiness_check,
                connector=dependencies.connector,
                process_factory=dependencies.process_factory,
                clock=dependencies.clock,
                timeout_seconds=dependencies.timeout_seconds,
                repeated_samples=dependencies.repeated_samples,
                order_field_factory=dependencies.order_field_factory,
                action_field_factory=dependencies.action_field_factory,
            )
        except CtpSharedManagedRuntimeError:
            raise
        except Exception as exc:
            reason = getattr(exc, "reason", None)
            if type(reason) is str:
                _reject("simnow_session_" + reason)
            _reject("simnow_session_open_rejected")


@dataclass(frozen=True, repr=False)
class CtpProductionManagedSessionAdapter:
    """Typed live entry point that remains closed without native/session authority."""

    registration: CtpProductionExecutionRegistration = field(repr=False)

    def open_session(self, effective: EffectiveRuntimeConfig, registry: RuntimeRegistry) -> None:
        if type(self.registration) is not CtpProductionExecutionRegistration:
            _reject("production_session_registration_required")
        if self.registration.runtime_registration is not effective.registration:
            _reject("production_session_registration_mismatch")
        try:
            _require_production_registration_seal(self.registration)
        except Exception:
            _reject("production_session_registration_invalid")
        if (effective.mode, effective.preset) != _PRODUCTION:
            _reject("production_session_mode_mismatch")
        try:
            if (
                registry.require_runtime_dir(effective.config.strategy_dir)
                is not effective.registration
            ):
                _reject("production_session_runtime_mismatch")
        except CtpSharedManagedRuntimeError:
            raise
        except Exception:
            _reject("production_session_runtime_mismatch")
        # The existing production composition is a pure scope selector. It has
        # no production-native client, external account writer fence, managed
        # session owner, or durable OrderRef/action journal. Reject before a
        # front probe, credential extraction, SDK import, or client factory.
        _reject("production_native_session_authority_unavailable")


@dataclass(frozen=True, repr=False)
class CtpSharedManagedSessionContext:
    """Freshness and isolation key for one opened mode-specific session."""

    scope: CtpModeScopeBinding = field(repr=False)
    mode_registration_digest: str
    approval_scope_digest: str
    journal_scope_digest: str
    state_partition: str
    context_digest: str

    @classmethod
    def for_simnow(
        cls,
        scope: CtpModeScopeBinding,
        registration: CtpSimulationExecutionRegistration,
        journal_scope_digest: str,
    ) -> "CtpSharedManagedSessionContext":
        if type(registration) is not CtpSimulationExecutionRegistration:
            _reject("simnow_session_registration_invalid")
        facts = {
            "approval_scope_digest": registration.digest,
            "journal_scope_digest": journal_scope_digest,
            "mode": scope.mode,
            "mode_registration_digest": registration.digest,
            "preset": scope.preset,
            "scope_digest": scope.scope_digest,
        }
        digest = hashlib.sha256(_SESSION_DOMAIN + _canonical(facts)).hexdigest()
        partition = "ctp-managed/{0}/{1}/{2}".format(scope.mode, scope.preset, digest[:24])
        return cls(
            scope=scope,
            mode_registration_digest=registration.digest,
            approval_scope_digest=registration.digest,
            journal_scope_digest=journal_scope_digest,
            state_partition=partition,
            context_digest=digest,
        )

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "approval_scope_digest": self.approval_scope_digest,
            "context_digest": self.context_digest,
            "execution_authorized": False,
            "journal_scope_digest": self.journal_scope_digest,
            "mode": self.scope.mode,
            "mode_registration_digest": self.mode_registration_digest,
            "order_submission_authorized": False,
            "preset": self.scope.preset,
            "scope_digest": self.scope.scope_digest,
            "state_partition": self.state_partition,
        }


@dataclass(frozen=True, repr=False)
class CtpSharedManagedRuntime:
    """The mode-selected runtime plus a freshness-checked shared context."""

    context: CtpSharedManagedSessionContext = field(repr=False)
    _mode_runtime: CtpSimNowManagedRuntime = field(repr=False, compare=False)
    _effective: EffectiveRuntimeConfig = field(repr=False, compare=False)
    _registry: RuntimeRegistry = field(repr=False, compare=False)

    def require_current(self) -> None:
        """Check public route/account/contract freshness, not secret rotation.

        Password and authentication-code freshness belongs to the SimNow
        port's typed per-action credential-binding refresh and approval
        callback. This wrapper does not expose or hash those secret values.
        """

        require_fresh_shared_managed_runtime(self, self._effective, self._registry)

    @property
    def session(self) -> Any:
        self.require_current()
        return self._mode_runtime.session

    def close(self) -> None:
        self._mode_runtime.close()

    def __enter__(self) -> "CtpSharedManagedRuntime":
        self.require_current()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _simnow_context(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    runtime: CtpSimNowManagedRuntime,
) -> CtpSharedManagedSessionContext:
    if type(runtime) is not CtpSimNowManagedRuntime:
        _reject("simnow_session_result_invalid")
    selection = runtime.selection
    if (
        type(getattr(selection, "execution_registration", None))
        is not CtpSimulationExecutionRegistration
    ):
        _reject("simnow_session_result_invalid")
    registration = selection.execution_registration
    pair = (registration.md_front, registration.td_front)
    if (
        registration.runtime_registration is not effective.registration
        or registration.environment != "simnow"
        or registration.config_digest != effective.config.config_digest
        or registration.effective_digest != effective.effective_digest
        or (effective.mode, effective.preset) != _SIMULATION
    ):
        _reject("simnow_session_scope_mismatch")
    try:
        scope = bind_ctp_mode_scope(effective, registry, selected_front_pair=pair)
        journal = _execution_journal_scope(effective, registration)
    except Exception:
        _reject("simnow_session_scope_stale")
    if scope.mode != _SIMULATION[0] or scope.preset != _SIMULATION[1]:
        _reject("simnow_session_mode_mismatch")
    return CtpSharedManagedSessionContext.for_simnow(scope, registration, journal.digest)


def require_fresh_shared_managed_runtime(
    runtime: CtpSharedManagedRuntime,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> None:
    """Reject a session/context when the sealed mode, config, pair or journal changed."""

    if type(runtime) is not CtpSharedManagedRuntime:
        _reject("shared_runtime_required")
    try:
        effective = _require_current_effective_runtime_config(effective, registry)
        registration, _ = _require_shared_runner_contract(effective, registry)
        if registration is not runtime._effective.registration:
            _reject("shared_runtime_stale")
        current = _simnow_context(effective, registry, runtime._mode_runtime)
    except CtpSharedManagedRuntimeError:
        raise
    except CtpSharedManagedRunnerError:
        _reject("shared_runtime_stale")
    except Exception:
        _reject("shared_runtime_stale")
    if current != runtime.context:
        _reject("shared_runtime_stale")


def open_shared_ctp_managed_runtime(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    simnow_adapter: Optional[CtpSimNowManagedSessionAdapter] = None,
    production_adapter: Optional[CtpProductionManagedSessionAdapter] = None,
) -> CtpSharedManagedRuntime:
    """Open the session selected solely by the fresh sealed config mode.

    The common profile and runner contract is checked before entering either
    mode adapter. SimNow reuses the existing full managed runtime. Production
    enters its typed adapter and currently rejects before probes, credentials,
    SDK imports or native client construction.
    """

    try:
        effective = _require_current_effective_runtime_config(effective, registry)
        _require_shared_runner_contract(effective, registry)
    except CtpSharedManagedRunnerError:
        _reject("shared_runner_contract_rejected")
    except Exception:
        _reject("shared_runner_contract_rejected")

    if (effective.mode, effective.preset) == _SIMULATION:
        if type(simnow_adapter) is not CtpSimNowManagedSessionAdapter:
            _reject("simnow_session_adapter_required")
        mode_runtime = simnow_adapter.open_session(effective, registry)
        try:
            context = _simnow_context(effective, registry, mode_runtime)
        except Exception:
            try:
                mode_runtime.close()
            except Exception:
                pass
            _reject("simnow_session_scope_rejected")
        result = CtpSharedManagedRuntime(context, mode_runtime, effective, registry)
        try:
            require_fresh_shared_managed_runtime(result, effective, registry)
        except Exception:
            try:
                mode_runtime.close()
            except Exception:
                pass
            raise
        return result

    if (effective.mode, effective.preset) == _PRODUCTION:
        if type(production_adapter) is not CtpProductionManagedSessionAdapter:
            _reject("production_session_adapter_required")
        production_adapter.open_session(effective, registry)
        _reject("production_session_open_unexpected_return")

    _reject("unsupported_mode_preset")


__all__ = [
    "CtpProductionManagedSessionAdapter",
    "CtpSharedManagedRuntime",
    "CtpSharedManagedRuntimeError",
    "CtpSharedManagedSessionContext",
    "CtpSimNowManagedSessionAdapter",
    "CtpSimNowManagedSessionDependencies",
    "open_shared_ctp_managed_runtime",
    "require_fresh_shared_managed_runtime",
]
