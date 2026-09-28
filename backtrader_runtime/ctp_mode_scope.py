"""Mode-tagged, non-authorizing scope binding for canonical CTP config.

The binder records which code-owned CTP profile and exact config scope were
selected. Its result carries no provider, credential, execution, or write
authority and is not accepted by a session or runner.
"""

from __future__ import annotations

import hashlib
import json
import re
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .config import CtpPrivateConfig
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FRONT_PAIRS = 8
_SCOPE_DOMAIN = b"backtrader-ctp-mode-scope-v1\0"
_ACCOUNT_DOMAIN = b"backtrader-ctp-mode-account-v1\0"
_FRONT_SET_DOMAIN = b"backtrader-ctp-mode-front-pair-set-v1\0"
_FRONT_DOMAIN = b"backtrader-ctp-mode-front-pair-v1\0"
_MODE_PRESETS = {
    ("simulation", "sandbox"),
    ("live", "managed_live_direct"),
}
_MODE_PROFILE_PAIRS = {
    ("simulation", "sandbox"): ("live", "managed_live_direct"),
    ("live", "managed_live_direct"): ("simulation", "sandbox"),
}
_SCOPE_SEALS: Dict[int, Tuple[Any, str]] = {}


class CtpModeScopeError(ValueError):
    """Redacted rejection from the mode-aware CTP scope binder."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpModeScopeError(reason) from None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _require_sha256(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_" + name)
    return value


def _front(value: Any) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        _reject("front_pair_set_invalid")
    return value


def _configured_front_pairs(private: CtpPrivateConfig) -> Tuple[Tuple[str, str], ...]:
    raw_pairs = private.front_pairs
    if type(raw_pairs) is not tuple or not 1 <= len(raw_pairs) <= _MAX_FRONT_PAIRS:
        _reject("front_pair_set_invalid")
    pairs = []
    seen = set()
    for item in raw_pairs:
        if not isinstance(item, Mapping) or set(item) != {"md_front", "td_front"}:
            _reject("front_pair_set_invalid")
        pair = (_front(item["md_front"]), _front(item["td_front"]))
        if pair in seen:
            _reject("front_pair_set_invalid")
        seen.add(pair)
        pairs.append(pair)
    return tuple(pairs)


def _account_binding_sha256(private: CtpPrivateConfig) -> str:
    broker_id = getattr(private, "broker_id", None)
    user_id = getattr(private, "user_id", None)
    if (
        type(broker_id) is not str
        or not broker_id
        or type(user_id) is not str
        or not user_id
    ):
        _reject("account_scope_invalid")
    return hashlib.sha256(
        _ACCOUNT_DOMAIN + _canonical({"broker_id": broker_id, "user_id": user_id})
    ).hexdigest()


def _front_pair_set_sha256(pairs: Tuple[Tuple[str, str], ...]) -> str:
    return hashlib.sha256(_FRONT_SET_DOMAIN + _canonical(pairs)).hexdigest()


def _selected_front_pair_sha256(pair: Tuple[str, str]) -> str:
    return hashlib.sha256(_FRONT_DOMAIN + _canonical(pair)).hexdigest()


def _require_profile_pair(
    registration: RegisteredRuntime, mode: str, preset: str
) -> RuntimeProfile:
    profile = registration.profile_for(mode, preset)
    other_mode, other_preset = _MODE_PROFILE_PAIRS[(mode, preset)]
    other = registration.profile_for(other_mode, other_preset)
    if type(profile) is not RuntimeProfile:
        _reject("shared_ctp_runner_profile_pair_required")
    if profile.runner_module is None:
        _reject("runner_not_registered")
    if type(other) is not RuntimeProfile:
        _reject("shared_ctp_runner_profile_pair_required")
    if (
        profile.mode != mode
        or profile.preset != preset
        or other.mode != other_mode
        or other.preset != other_preset
    ):
        _reject("profile_scope_mismatch")
    if other.runner_module is None:
        _reject("runner_not_registered")
    if (
        profile.runner_module != other.runner_module
        or profile.runner_entrypoint != other.runner_entrypoint
    ):
        _reject("shared_ctp_runner_mismatch")
    for candidate in (profile, other):
        if (
            candidate.allowed_parameter_keys != ()
            or candidate.allowed_secrets_refs != ("config_yaml",)
            or candidate.capability_modules != ()
            or candidate.offline_managed_execution is not False
        ):
            _reject("profile_scope_policy_mismatch")
    if profile.mode == "live" and profile.approval_receipt_digest is None:
        _reject("live_profile_receipt_required")
    if profile.sandbox_write_policy == "receipt_required" and (
        profile.approval_receipt_digest is None
    ):
        _reject("profile_receipt_mismatch")
    return profile


def _require_canonical_private_config(effective: EffectiveRuntimeConfig) -> CtpPrivateConfig:
    config = effective.config
    private = getattr(config, "ctp", None)
    if type(private) is not CtpPrivateConfig or getattr(config, "ctp_production", None) is not None:
        _reject("canonical_ctp_config_required")
    legacy = getattr(config, "ctp_simnow", None)
    if legacy is not None and legacy is not private:
        _reject("ctp_private_config_alias_mismatch")
    if config.secrets_ref != "config_yaml" or tuple(config.parameters) != ():
        _reject("canonical_ctp_config_policy_mismatch")
    if (
        type(private.instrument_id) is not str
        or not private.instrument_id
        or type(private.exchange_id) is not str
        or not private.exchange_id
        or type(private.hedge_flag) is not str
        or private.hedge_flag not in ("1", "2", "3")
    ):
        _reject("contract_scope_invalid")
    return private


def _scope_payload(scope: "CtpModeScopeBinding") -> Dict[str, Any]:
    return {
        "account_binding_sha256": scope.account_binding_sha256,
        "arming_authorized": scope.arming_authorized,
        "config_digest": scope.config_digest,
        "cancellation_authorized": scope.cancellation_authorized,
        "credentials_resolved": scope.credentials_resolved,
        "execution_authorized": scope.execution_authorized,
        "effective_digest": scope.effective_digest,
        "exchange_id": scope.exchange_id,
        "external_writes_authorized": scope.external_writes_authorized,
        "front_pair_set_sha256": scope.front_pair_set_sha256,
        "instrument_id": scope.instrument_id,
        "mode": scope.mode,
        "order_submission_authorized": scope.order_submission_authorized,
        "preset": scope.preset,
        "production_writes_authorized": scope.production_writes_authorized,
        "profile_approval_receipt_digest": scope.profile_approval_receipt_digest,
        "profile_digest": scope.profile_digest,
        "provider_access_authorized": scope.provider_access_authorized,
        "registration_digest": scope.registration_digest,
        "runner_entrypoint": scope.runner_entrypoint,
        "runner_module": scope.runner_module,
        "runtime_id": scope.runtime_id,
        "selected_front_pair_sha256": scope.selected_front_pair_sha256,
        "strategy_id": scope.strategy_id,
        "hedge_flag": scope.hedge_flag,
    }


def _scope_digest(scope: "CtpModeScopeBinding") -> str:
    return hashlib.sha256(_SCOPE_DOMAIN + _canonical(_scope_payload(scope))).hexdigest()


@dataclass(frozen=True, repr=False)
class CtpModeScopeBinding:
    """Immutable mode-tagged scope facts with all operational authority false."""

    mode: str
    preset: str
    runtime_id: str
    strategy_id: str
    runner_module: str
    runner_entrypoint: str
    registration_digest: str
    profile_digest: str
    profile_approval_receipt_digest: Optional[str]
    config_digest: str
    effective_digest: str
    account_binding_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    front_pair_set_sha256: str
    selected_front_pair: Tuple[str, str] = field(repr=False)
    selected_front_pair_sha256: str
    provider_access_authorized: bool = field(default=False, init=False)
    credentials_resolved: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    production_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)
    scope_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (self.mode, self.preset) not in _MODE_PRESETS:
            _reject("unsupported_mode_preset")
        if (
            type(self.runtime_id) is not str
            or not self.runtime_id
            or type(self.strategy_id) is not str
            or not self.strategy_id
            or type(self.runner_module) is not str
            or not self.runner_module
            or type(self.runner_entrypoint) is not str
            or not self.runner_entrypoint
        ):
            _reject("invalid_scope_identity")
        for value, name in (
            (self.registration_digest, "registration_digest"),
            (self.profile_digest, "profile_digest"),
            (self.config_digest, "config_digest"),
            (self.effective_digest, "effective_digest"),
            (self.account_binding_sha256, "account_binding_sha256"),
            (self.front_pair_set_sha256, "front_pair_set_sha256"),
            (self.selected_front_pair_sha256, "selected_front_pair_sha256"),
        ):
            _require_sha256(value, name)
        if self.profile_approval_receipt_digest is not None:
            _require_sha256(self.profile_approval_receipt_digest, "profile_receipt_digest")
        if (
            type(self.selected_front_pair) is not tuple
            or len(self.selected_front_pair) != 2
            or any(type(value) is not str or not value for value in self.selected_front_pair)
            or self.selected_front_pair_sha256
            != _selected_front_pair_sha256(self.selected_front_pair)
        ):
            _reject("selected_front_pair_binding_mismatch")
        if any(
            value is not False
            for value in (
                self.provider_access_authorized,
                self.credentials_resolved,
                self.execution_authorized,
                self.external_writes_authorized,
                self.production_writes_authorized,
                self.order_submission_authorized,
                self.cancellation_authorized,
                self.arming_authorized,
            )
        ):
            _reject("authorizing_facts_forbidden")
        object.__setattr__(self, "scope_digest", _scope_digest(self))

    def __bool__(self) -> bool:
        raise TypeError("CTP mode scope binding is non-authorizing evidence")

    def as_public_dict(self) -> Dict[str, Any]:
        """Return a redacted, JSON-safe view without account IDs or front URLs."""

        return {
            "arming_authorized": False,
            "cancellation_authorized": False,
            "config_digest": self.config_digest,
            "credentials_resolved": False,
            "effective_digest": self.effective_digest,
            "execution_authorized": False,
            "exchange_id": self.exchange_id,
            "external_writes_authorized": False,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "mode": self.mode,
            "order_submission_authorized": False,
            "preset": self.preset,
            "production_writes_authorized": False,
            "profile_approval_receipt_digest": self.profile_approval_receipt_digest,
            "profile_digest": self.profile_digest,
            "provider_access_authorized": False,
            "registration_digest": self.registration_digest,
            "runner_entrypoint": self.runner_entrypoint,
            "runner_module": self.runner_module,
            "runtime_id": self.runtime_id,
            "selected_front_pair_sha256": self.selected_front_pair_sha256,
            "strategy_id": self.strategy_id,
        }


def bind_ctp_mode_scope(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    selected_front_pair: Tuple[str, str],
) -> CtpModeScopeBinding:
    """Bind a selected pair to the fresh canonical config and exact mode profile.

    This function performs no network, credential-store, SDK, runner, or session
    operation. ``selected_front_pair`` must already be an exact member of the
    freshly sealed ordered candidate set.
    """

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    if registry.trusted is not True:
        _reject("trusted_registry_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
    except Exception:
        _reject("sealed_runtime_rejected")
    if (effective.mode, effective.preset) not in _MODE_PRESETS:
        _reject("unsupported_mode_preset")
    try:
        registered = registry.require_runtime_dir(effective.config.strategy_dir)
    except Exception:
        _reject("runtime_registration_mismatch")
    if registered is not effective.registration or type(registered) is not RegisteredRuntime:
        _reject("runtime_registration_mismatch")

    profile = _require_profile_pair(registered, effective.mode, effective.preset)
    if (
        effective.profile is not profile
        or registered.strategy_id != effective.config.strategy_id
        or registered.allowed_presets != ()
        or registered.allowed_parameter_keys != ()
        or registered.allowed_secrets_refs != ("none",)
        or registered.available_capabilities != ()
        or registered.offline_managed_execution is not False
        or registered.sandbox_write_policy != "deny"
        or registered.approval_receipt_digest is not None
        or registered.runner_module is not None
        or registered.capability_modules != ()
    ):
        _reject("profile_registration_binding_mismatch")

    try:
        current = validate_runtime_config(registered.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
    except Exception:
        _reject("fresh_sealed_runtime_rejected")
    if (
        current.registration is not registered
        or current.profile is not profile
        or current.mode != effective.mode
        or current.preset != effective.preset
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
        or current.profile.digest != profile.digest
        or current.profile.approval_receipt_digest != profile.approval_receipt_digest
    ):
        _reject("fresh_sealed_runtime_changed")

    private = _require_canonical_private_config(current)
    pairs = _configured_front_pairs(private)
    if (
        type(selected_front_pair) is not tuple
        or len(selected_front_pair) != 2
        or any(type(value) is not str for value in selected_front_pair)
        or selected_front_pair not in pairs
    ):
        _reject("selected_front_pair_outside_config")

    binding = CtpModeScopeBinding(
        mode=current.mode,
        preset=current.preset,
        runtime_id=registered.runtime_id or "",
        strategy_id=current.config.strategy_id,
        runner_module=profile.runner_module or "",
        runner_entrypoint=profile.runner_entrypoint,
        registration_digest=registered.digest,
        profile_digest=profile.digest,
        profile_approval_receipt_digest=profile.approval_receipt_digest,
        config_digest=current.config.config_digest,
        effective_digest=current.effective_digest,
        account_binding_sha256=_account_binding_sha256(private),
        instrument_id=private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        front_pair_set_sha256=_front_pair_set_sha256(pairs),
        selected_front_pair=selected_front_pair,
        selected_front_pair_sha256=_selected_front_pair_sha256(selected_front_pair),
    )
    _seal_scope(binding)
    return binding


def _seal_scope(scope: CtpModeScopeBinding) -> None:
    identifier = id(scope)

    def discard(reference: Any) -> None:
        current = _SCOPE_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _SCOPE_SEALS.pop(identifier, None)

    reference = weakref.ref(scope, discard)
    _SCOPE_SEALS[identifier] = (reference, scope.scope_digest)


def require_ctp_mode_scope_binding(scope: CtpModeScopeBinding) -> None:
    """Verify binder provenance and immutability; this grants no authority."""

    if type(scope) is not CtpModeScopeBinding:
        _reject("scope_binding_required")
    current = _SCOPE_SEALS.get(id(scope))
    if current is None or current[0]() is not scope:
        _reject("scope_binding_provenance_invalid")
    try:
        type(scope).__post_init__(scope)
        digest = _scope_digest(scope)
    except Exception:
        _reject("scope_binding_provenance_invalid")
    if digest != current[1] or scope.scope_digest != current[1]:
        _reject("scope_binding_provenance_invalid")


__all__ = [
    "CtpModeScopeBinding",
    "CtpModeScopeError",
    "bind_ctp_mode_scope",
    "require_ctp_mode_scope_binding",
]
