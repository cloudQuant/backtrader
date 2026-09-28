"""Concrete, opt-in resolver for sealed CTP managed-action scopes.

The resolver reruns the repository's strict runtime/config seals and the
mode-specific CTP admission contract on every call.  It accepts one fixed
front pair selected by an upstream reviewed composition; it never probes,
selects a fallback, reads credentials, imports a native SDK, or dispatches.

This is still an in-process local contract.  The current callback-session API
does not expose the host pair actually used by an active native session, so a
composition must retain and verify that continuity outside this resolver.
The default inventory's sandbox is zero-write and its managed-live profile is
unavailable; neither is made runnable here.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from typing import Any, Tuple

from .config import CtpPrivateConfig
from .ctp_managed_action_authority import CtpManagedActionScopeV1
from .ctp_production_execution_admission import (
    CtpProductionExecutionConfigBinding,
    CtpProductionExecutionRegistration,
    require_ctp_production_execution_config_binding,
)
from .ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    ctp_simnow_front_pair_set_sha256,
)
from .ctp_simulation_execution import (
    CtpSimulationExecutionRegistration,
    require_ctp_simulation_execution_admission,
)
from .policy import MANAGED_WRITE_CAPABILITIES
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


_ACCOUNT_REF_DOMAIN = b"backtrader-ctp-managed-account-ref.v1\0"
_FRONT_PAIR_DOMAIN = b"backtrader-ctp-managed-front-pair.v1\0"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_TRADING_DAY_RE = re.compile(r"^[0-9]{8}$", re.ASCII)
_HEX_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MODE_SCOPE = {
    "simulation": ("simnow", "simulation", "sandbox"),
    "live": ("production", "live", "managed_live_direct"),
}


class CtpManagedActionScopeResolutionError(RuntimeError):
    """Redacted fail-closed result for resolving a current CTP action scope."""


def _reject() -> None:
    raise CtpManagedActionScopeResolutionError("sealed CTP action scope is unavailable")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def ctp_managed_account_ref_v1(broker_id: Any, user_id: Any) -> str:
    """Derive an opaque account reference from validated CTP account selectors.

    Canonical JSON with an explicit domain prefix avoids ambiguous concatenated
    identities.  The returned value never contains either selector.
    """

    if (
        type(broker_id) is not str
        or type(user_id) is not str
        or _ID_RE.fullmatch(broker_id) is None
        or _ID_RE.fullmatch(user_id) is None
    ):
        _reject()
    payload = _canonical_bytes({"broker_id": broker_id, "user_id": user_id})
    digest = hashlib.sha256(_ACCOUNT_REF_DOMAIN + payload).hexdigest()
    return "ctp-account-ref.v1:" + digest


def _execution_scope_type() -> type:
    """Load the exact optional V17 scope type without touching the SDK by default."""

    try:
        if importlib.metadata.version("bt_api_execution") != "0.2.0":
            _reject()
        from bt_api_execution.contracts import ExecutionScope
    except CtpManagedActionScopeResolutionError:
        raise
    except Exception:
        _reject()
    return ExecutionScope


def _valid_trading_day(value: Any) -> bool:
    if type(value) is not str or _TRADING_DAY_RE.fullmatch(value) is None:
        return False
    try:
        import datetime

        datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _account_scope_matches(execution_scope: Any, config_private: CtpPrivateConfig) -> Any:
    scope_type = _execution_scope_type()
    if (
        type(execution_scope) is not scope_type
        or type(getattr(execution_scope, "provider", None)) is not str
        or type(getattr(execution_scope, "environment", None)) is not str
        or type(getattr(execution_scope, "strategy_id", None)) is not str
        or not _valid_trading_day(getattr(execution_scope, "trading_day", None))
    ):
        _reject()
    account_ref = ctp_managed_account_ref_v1(config_private.broker_id, config_private.user_id)
    try:
        expected = scope_type(
            provider="ctp",
            environment=execution_scope.environment,
            account_ref=account_ref,
            strategy_id=execution_scope.strategy_id,
            trading_day=execution_scope.trading_day,
        )
    except Exception:
        _reject()
    # Mode mapping and strategy are checked by the caller; reconstructing with
    # those expected values prevents trusting a caller's account-key assertion.
    if (
        execution_scope.to_payload() != expected.to_payload()
        or execution_scope.key != expected.key
        or execution_scope.account_key != expected.account_key
        or not execution_scope.account_key.startswith("account:")
        or _HEX_RE.fullmatch(execution_scope.account_key[len("account:") :]) is None
    ):
        _reject()
    return expected


def _execution_scope_snapshot(execution_scope: Any) -> Tuple[bytes, str, str]:
    scope_type = _execution_scope_type()
    if type(execution_scope) is not scope_type:
        _reject()
    try:
        payload = execution_scope.to_payload()
        key = execution_scope.key
        account_key = execution_scope.account_key
        if type(payload) is not dict or set(payload) != {
            "provider",
            "environment",
            "account_ref",
            "strategy_id",
            "trading_day",
        }:
            _reject()
        if any(value is not None and type(value) is not str for value in payload.values()):
            _reject()
        if type(key) is not str or type(account_key) is not str:
            _reject()
        return _canonical_bytes(payload), key, account_key
    except CtpManagedActionScopeResolutionError:
        raise
    except Exception:
        _reject()


def _front_pair_sha256(pair: Tuple[str, str]) -> str:
    return hashlib.sha256(_FRONT_PAIR_DOMAIN + _canonical_bytes(list(pair))).hexdigest()


def _simnow_legacy_admission_account_digest(private: CtpPrivateConfig) -> str:
    """Build the legacy admission field only; SDK account scope uses v1 helper."""

    short = hashlib.sha256(
        "{0}:{1}".format(private.broker_id, private.user_id).encode("utf-8")
    ).hexdigest()[:16]
    return hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


class SealedCtpManagedActionScopeResolverV1:
    """Rerun sealed config and CTP mode admission for one fixed selected pair.

    ``mode_admission`` is an exact code-owned ``CtpSimNowManagedExecutionPolicy``
    or sealed-config ``CtpProductionExecutionRegistration``.  The object is
    pinned to this resolver instance and must reference the exact registered
    runtime.  Its Python constructor cannot prove deployment ownership; the
    composition must supply it from reviewed code.
    """

    def __init__(
        self,
        registry: RuntimeRegistry,
        runtime_registration: RegisteredRuntime,
        mode_admission: Any,
        selected_front_pair: Tuple[str, str],
        execution_scope: Any,
    ) -> None:
        if (
            type(registry) is not RuntimeRegistry
            or registry.trusted is not True
            or type(runtime_registration) is not RegisteredRuntime
            or registry.require_runtime_dir(runtime_registration.runtime_dir)
            is not runtime_registration
            or type(selected_front_pair) is not tuple
            or len(selected_front_pair) != 2
            or any(
                type(item) is not str or not item or len(item) > 512 for item in selected_front_pair
            )
        ):
            _reject()
        if type(mode_admission) is CtpSimNowManagedExecutionPolicy:
            mode = "simulation"
            if mode_admission.runtime_registration is not runtime_registration:
                _reject()
        elif type(mode_admission) is CtpProductionExecutionRegistration:
            mode = "live"
            if (
                mode_admission.runtime_registration is not runtime_registration
                or mode_admission.scope_binding_mode != "sealed_config"
            ):
                _reject()
        else:
            _reject()
        self._registry = registry
        self._registration = runtime_registration
        self._mode_admission = mode_admission
        self._mode = mode
        self._environment, self._mode_name, self._preset = _MODE_SCOPE[mode]
        self._selected_front_pair = selected_front_pair
        self._execution_scope = execution_scope
        self._execution_scope_snapshot = _execution_scope_snapshot(execution_scope)
        self._check_registered_mode_declaration()
        self._baseline = self._derive_current_scope()

    def _check_registered_mode_declaration(self) -> None:
        registration = self._registration
        if registration.profiles:
            profile = registration.profile_for(self._mode_name, self._preset)
            unavailable = any(
                item.mode == self._mode_name and item.preset == self._preset
                for item in registration.unavailable_mode_profiles
            )
            if unavailable or type(profile) is not RuntimeProfile:
                _reject()
            if self._mode == "simulation":
                if profile.sandbox_write_policy != "receipt_required":
                    _reject()
            elif (
                profile.available_capabilities != MANAGED_WRITE_CAPABILITIES
                or profile.sandbox_write_policy != "deny"
                or profile.allowed_secrets_refs != ("config_yaml",)
            ):
                _reject()
            return
        if (
            any(
                item.mode == self._mode_name and item.preset == self._preset
                for item in registration.unavailable_mode_profiles
            )
            or self._preset not in registration.allowed_presets
        ):
            _reject()

    def _fresh_effective(self) -> EffectiveRuntimeConfig:
        try:
            effective = validate_runtime_config(self._registration.runtime_dir, self._registry)
            require_effective_runtime_config_seal(effective, self._registry)
        except Exception:
            _reject()
        if (
            type(effective) is not EffectiveRuntimeConfig
            or effective.registration is not self._registration
            or effective.mode != self._mode_name
            or effective.preset != self._preset
            or effective.config.strategy_id != self._registration.strategy_id
        ):
            _reject()
        return effective

    def _derive_current_scope(self) -> CtpManagedActionScopeV1:
        if _execution_scope_snapshot(self._execution_scope) != self._execution_scope_snapshot:
            _reject()
        effective = self._fresh_effective()
        private = effective.config.ctp
        if (
            type(private) is not CtpPrivateConfig
            or effective.config.ctp_production is not None
            or (
                self._mode == "simulation"
                and effective.config.ctp_simnow is not None
                and effective.config.ctp_simnow is not private
            )
            or (self._mode == "live" and effective.config.ctp_simnow is not None)
        ):
            _reject()
        execution_scope = _account_scope_matches(self._execution_scope, private)
        if (
            execution_scope.provider != "ctp"
            or execution_scope.environment != self._environment
            or execution_scope.strategy_id != effective.config.strategy_id
        ):
            _reject()
        candidate_pairs = tuple(
            (pair["md_front"], pair["td_front"]) for pair in private.front_pairs
        )
        if candidate_pairs.count(self._selected_front_pair) != 1:
            _reject()

        if self._mode == "simulation":
            scope_facts = self._derive_simulation_scope(effective, private, candidate_pairs)
        else:
            scope_facts = self._derive_live_scope(effective)
        account_key = execution_scope.account_key
        account_fingerprint = account_key.partition(":")[2]
        if _HEX_RE.fullmatch(account_fingerprint) is None:
            _reject()
        return CtpManagedActionScopeV1(
            provider="ctp",
            environment=self._environment,
            mode=self._mode_name,
            preset=self._preset,
            runtime_id=self._registration.runtime_id or "",
            strategy_id=effective.config.strategy_id,
            runtime_registration_digest=self._registration.digest,
            mode_registration_digest=scope_facts["mode_registration_digest"],
            config_digest=effective.config.config_digest,
            effective_digest=effective.effective_digest,
            profile_digest=None if effective.profile is None else effective.profile.digest,
            account_fingerprint_sha256=account_fingerprint,
            front_pair_sha256=scope_facts["front_pair_sha256"],
            front_pair_set_sha256=scope_facts["front_pair_set_sha256"],
        )

    def _derive_simulation_scope(
        self,
        effective: EffectiveRuntimeConfig,
        private: CtpPrivateConfig,
        candidate_pairs: Tuple[Tuple[str, str], ...],
    ) -> dict[str, str]:
        policy = self._mode_admission
        if type(policy) is not CtpSimNowManagedExecutionPolicy:
            _reject()
        candidate_digest = ctp_simnow_front_pair_set_sha256(private.front_pairs)
        profile = effective.profile
        try:
            registration = CtpSimulationExecutionRegistration(
                runtime_registration=self._registration,
                environment="simnow",
                sdk_profile="config_front_pair",
                td_front=self._selected_front_pair[1],
                md_front=self._selected_front_pair[0],
                account_fingerprint_sha256=_simnow_legacy_admission_account_digest(private),
                allowed_secrets_ref=policy.allowed_secrets_ref,
                instrument_id=private.instrument_id,
                exchange_id=private.exchange_id,
                hedge_flag=private.hedge_flag,
                allowed_sides=policy.allowed_sides,
                quantity_step=policy.quantity_step,
                max_quantity=policy.max_quantity,
                max_gross_position=policy.max_gross_position,
                min_price=policy.min_price,
                max_price=policy.max_price,
                price_tick=policy.price_tick,
                approval_key_id=policy.approval_key_id,
                approval_ttl_seconds=policy.approval_ttl_seconds,
                front_pair_set_sha256=candidate_digest,
                config_digest=effective.config.config_digest,
                effective_digest=effective.effective_digest,
                profile_digest=None if profile is None else profile.digest,
                profile_approval_receipt_digest=(
                    None if profile is None else profile.approval_receipt_digest
                ),
            )
            require_ctp_simulation_execution_admission(effective, self._registry, registration)
        except Exception:
            _reject()
        # Candidate membership is independently checked above; avoid probing or
        # reconstructing a transport-based selection here.
        if candidate_pairs.count(self._selected_front_pair) != 1:
            _reject()
        return {
            "mode_registration_digest": registration.digest,
            "front_pair_sha256": _front_pair_sha256(self._selected_front_pair),
            "front_pair_set_sha256": candidate_digest,
        }

    def _derive_live_scope(self, effective: EffectiveRuntimeConfig) -> dict[str, str]:
        registration = self._mode_admission
        if (
            type(registration) is not CtpProductionExecutionRegistration
            or registration.scope_binding_mode != "sealed_config"
        ):
            _reject()
        try:
            binding = require_ctp_production_execution_config_binding(
                effective.config,
                self._registry,
                registration,
                selected_front_pair=self._selected_front_pair,
                effective_runtime=effective,
            )
        except Exception:
            _reject()
        if (
            type(binding) is not CtpProductionExecutionConfigBinding
            or (binding.md_front, binding.td_front) != self._selected_front_pair
        ):
            _reject()
        return {
            "mode_registration_digest": binding.registration_digest,
            "front_pair_sha256": binding.front_pair_sha256,
            "front_pair_set_sha256": binding.front_pair_set_sha256,
        }

    def resolve(self, command: Any, execution_scope: Any) -> CtpManagedActionScopeV1:
        """Revalidate the full current seal and return the unchanged pinned scope."""

        if execution_scope is not self._execution_scope:
            _reject()
        try:
            if importlib.metadata.version("bt_api_execution") != "0.2.0":
                _reject()
            from bt_api_execution.store import CtpDispatchCommand
        except CtpManagedActionScopeResolutionError:
            raise
        except Exception:
            _reject()
        if type(command) is not CtpDispatchCommand:
            _reject()
        if (
            command.account_key != self._execution_scope.account_key
            or command.scope_key != self._execution_scope.key
            or command.trading_day != self._execution_scope.trading_day
        ):
            _reject()
        current = self._derive_current_scope()
        if (
            current.to_payload() != self._baseline.to_payload()
            or current.digest != self._baseline.digest
        ):
            _reject()
        return current

    def validate_action_context(
        self,
        command: Any,
        execution_scope: Any,
        *,
        session_binding: Any,
        session_broker_id: Any,
        session_user_id: Any,
    ) -> CtpManagedActionScopeV1:
        """Bind request and Store-readback login identity to current sealed CTP config.

        A valid signature authorizes only the signed action. It does not prove
        that the request's account or contract fields match the private config
        or the account that logged in. This method is required by the authority
        adapter and is also called at the final SDK lease boundary.
        """

        current = self.resolve(command, execution_scope)
        self._validate_session_and_request(
            operation=getattr(command, "operation", None),
            payload=getattr(command, "request_payload", None),
            execution_scope=execution_scope,
            session_binding=session_binding,
            session_broker_id=session_broker_id,
            session_user_id=session_user_id,
            expected_scope=current,
        )
        return current

    def validate_prepared_action_context(
        self,
        prepared: Any,
        execution_scope: Any,
        *,
        session_binding: Any,
        session_broker_id: Any,
        session_user_id: Any,
    ) -> CtpManagedActionScopeV1:
        """Validate a typed prepared action before its durable Store staging."""

        try:
            from bt_api_execution.ctp_single_worker_candidate import (
                CtpManagedPreparedDispatch,
            )
        except Exception:
            _reject()
        if type(prepared) is not CtpManagedPreparedDispatch:
            _reject()
        current = self._derive_current_scope()
        if (
            current.to_payload() != self._baseline.to_payload()
            or current.digest != self._baseline.digest
            or execution_scope is not self._execution_scope
        ):
            _reject()
        operation = {"submit": "SUBMIT", "cancel": "CANCEL"}.get(prepared.operation)
        if operation is None:
            _reject()
        self._validate_session_and_request(
            operation=operation,
            payload=prepared.request_payload,
            execution_scope=execution_scope,
            session_binding=session_binding,
            session_broker_id=session_broker_id,
            session_user_id=session_user_id,
            expected_scope=current,
        )
        return current

    def _validate_session_and_request(
        self,
        *,
        operation: Any,
        payload: Any,
        execution_scope: Any,
        session_binding: Any,
        session_broker_id: Any,
        session_user_id: Any,
        expected_scope: CtpManagedActionScopeV1,
    ) -> None:
        try:
            from bt_api_execution.store import CtpCallbackSessionBindingV1

            effective = self._fresh_effective()
        except Exception:
            _reject()
        if (
            type(session_binding) is not CtpCallbackSessionBindingV1
            or execution_scope is not self._execution_scope
            or effective.config.config_digest != expected_scope.config_digest
            or effective.effective_digest != expected_scope.effective_digest
            or type(session_broker_id) is not str
            or type(session_user_id) is not str
            or session_broker_id != effective.config.ctp.broker_id
            or session_user_id != effective.config.ctp.user_id
            or session_binding.account_key != execution_scope.account_key
            or session_binding.scope_key != execution_scope.key
            or session_binding.trading_day != execution_scope.trading_day
            or type(payload) is not dict
            or operation not in {"SUBMIT", "CANCEL"}
        ):
            _reject()
        private = effective.config.ctp
        expected = {
            "BrokerID": private.broker_id,
            "InvestorID": private.user_id,
            "UserID": private.user_id,
            "InstrumentID": private.instrument_id,
            "ExchangeID": private.exchange_id,
        }
        if any(
            type(payload.get(name)) is not str or payload.get(name) != value
            for name, value in expected.items()
        ):
            _reject()
        hedge_flag = payload.get("CombHedgeFlag")
        if operation == "SUBMIT":
            if type(hedge_flag) is not str or hedge_flag != private.hedge_flag:
                _reject()
        elif hedge_flag is not None and (
            type(hedge_flag) is not str or hedge_flag != private.hedge_flag
        ):
            _reject()


__all__ = [
    "CtpManagedActionScopeResolutionError",
    "SealedCtpManagedActionScopeResolverV1",
    "ctp_managed_account_ref_v1",
]
