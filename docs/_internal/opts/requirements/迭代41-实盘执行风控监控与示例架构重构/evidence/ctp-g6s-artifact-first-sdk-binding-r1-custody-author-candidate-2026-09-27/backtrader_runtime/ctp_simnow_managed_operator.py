"""Pure admission and configured-front selection for managed SimNow runs.

This module does not resolve credentials, import a CTP SDK, open a provider
session, or submit orders.  A future reviewed operator route must obtain its
immutable policy from code-owned inventory and must continue through the
separate approval, artifact, session, writer-fence, and reconciliation gates.
The only network-capable operation here is the bounded, credential-free TCP
probe of the exact candidate pairs in the sealed config.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from .config import CtpPrivateConfig
from .ctp_front_pair_probe import (
    CtpFrontPairProbeError,
    CtpFrontPairSelection,
    select_ctp_front_pair,
)
from .ctp_simulation_execution import (
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    require_ctp_simulation_execution_admission,
)
from .errors import RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FRONT_PAIR_SET_DOMAIN = b"backtrader-ctp-simnow-front-pair-set-v1\0"
_MAX_FRONT_PAIRS = 8
_REQUIRED_CAPABILITIES = ("execution", "risk", "monitor")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")


def _managed_selector_profile(
    registration: RegisteredRuntime, secrets_ref: str
) -> Optional[RuntimeProfile]:
    """Return the exact receipt-required profile, or validate legacy policy facts."""

    if registration.profiles:
        profile = registration.profile_for("simulation", "sandbox")
        if (
            type(profile) is not RuntimeProfile
            or profile.mode != "simulation"
            or profile.preset != "sandbox"
            or profile.allowed_parameter_keys != ()
            or profile.allowed_secrets_refs != (secrets_ref,)
            or profile.available_capabilities != _REQUIRED_CAPABILITIES
            or profile.approval_receipt_digest is None
            or profile.offline_managed_execution is not False
            or profile.sandbox_write_policy != "receipt_required"
        ):
            _reject("runtime_profile_policy_mismatch")
        # Profile-scoped registrations deliberately keep these legacy policy
        # fields inert. Never let them supply a fallback receipt or capability.
        if (
            registration.allowed_presets != ()
            or registration.allowed_parameter_keys != ()
            or registration.allowed_secrets_refs != ("none",)
            or registration.available_capabilities != ()
            or registration.offline_managed_execution is not False
            or registration.sandbox_write_policy != "deny"
            or registration.approval_receipt_digest is not None
        ):
            _reject("runtime_profile_legacy_policy_not_inert")
        return profile

    if (
        registration.allowed_presets != ("sandbox",)
        or registration.allowed_parameter_keys != ()
        or registration.allowed_secrets_refs != (secrets_ref,)
        or registration.sandbox_write_policy != "receipt_required"
        or registration.approval_receipt_digest is None
        or registration.available_capabilities != _REQUIRED_CAPABILITIES
        or registration.offline_managed_execution
    ):
        _reject("runtime_policy_mismatch")
    return None


class CtpSimNowManagedOperatorError(ValueError):
    """Redacted rejection from the offline SimNow managed-scope selector."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpSimNowManagedOperatorError(reason)


def ctp_simnow_front_pair_set_sha256(
    front_pairs: Sequence[Mapping[str, str]],
) -> str:
    """Digest the ordered, exact configured MD/TD pairs using the journal contract.

    The serialized value is ``[[md_front, td_front], ...]`` in config order,
    encoded as compact ASCII JSON and prefixed with the versioned domain
    separator.  No profile, set label, calendar, or time-derived value enters
    this identity.
    """

    if isinstance(front_pairs, (str, bytes)) or not isinstance(front_pairs, Sequence):
        _reject("front_pair_set_invalid")
    if not 1 <= len(front_pairs) <= _MAX_FRONT_PAIRS:
        _reject("front_pair_set_invalid")
    pairs = []
    seen = set()
    for item in front_pairs:
        if not isinstance(item, Mapping) or set(item) != {"md_front", "td_front"}:
            _reject("front_pair_set_invalid")
        md_front = item["md_front"]
        td_front = item["td_front"]
        if type(md_front) is not str or not md_front or type(td_front) is not str or not td_front:
            _reject("front_pair_set_invalid")
        pair = (md_front, td_front)
        if pair in seen:
            _reject("front_pair_set_invalid")
        seen.add(pair)
        pairs.append([md_front, td_front])
    serialized = json.dumps(pairs, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(_FRONT_PAIR_SET_DOMAIN + serialized).hexdigest()


@dataclass(frozen=True)
class CtpSimNowManagedExecutionPolicy:
    """Code-owned runtime admission, approval identity, and hard risk envelope.

    Production code must source this value from a reviewed inventory entry;
    account, configured front candidates, and contract scope are resolved from
    the freshly sealed canonical ``ctp:`` block on each invocation.  The policy
    deliberately contains no account, endpoint, or contract values, so an
    operator can update those values in ``config.yaml`` without a code change.
    Its numeric bounds remain the code-owned hard execution envelope.
    """

    runtime_registration: RegisteredRuntime
    allowed_sides: Tuple[str, ...]
    quantity_step: int
    max_quantity: int
    max_gross_position: int
    min_price: Decimal
    max_price: Decimal
    price_tick: Decimal
    approval_key_id: str
    environment: str = "simnow"
    approval_ttl_seconds: float = 30.0
    allowed_secrets_ref: str = "config_yaml"

    def __post_init__(self) -> None:
        if type(self.runtime_registration) is not RegisteredRuntime:
            _reject("code_owned_registration_required")
        registration = self.runtime_registration
        if (
            registration.allowed_presets != ("sandbox",)
            or registration.allowed_parameter_keys != ()
            or registration.allowed_secrets_refs != (self.allowed_secrets_ref,)
            or registration.sandbox_write_policy != "receipt_required"
            or registration.approval_receipt_digest is None
            or registration.available_capabilities != _REQUIRED_CAPABILITIES
            or registration.offline_managed_execution
        ):
            if registration.profiles:
                _managed_selector_profile(registration, self.allowed_secrets_ref)
            else:
                _reject("runtime_policy_mismatch")
        if self.allowed_secrets_ref != "config_yaml":
            _reject("invalid_secrets_reference")
        if self.environment != "simnow":
            _reject("environment_policy_mismatch")
        sides = tuple(self.allowed_sides)
        if (
            not sides
            or len(set(sides)) != len(sides)
            or any(side not in ("BUY", "SELL") for side in sides)
        ):
            _reject("risk_policy_invalid")
        object.__setattr__(self, "allowed_sides", sides)
        if (
            type(self.quantity_step) is not int
            or self.quantity_step <= 0
            or type(self.max_quantity) is not int
            or self.max_quantity <= 0
            or self.max_quantity % self.quantity_step
            or type(self.max_gross_position) is not int
            or self.max_gross_position < self.max_quantity
        ):
            _reject("risk_policy_invalid")
        try:
            minimum = Decimal(str(self.min_price))
            maximum = Decimal(str(self.max_price))
            tick = Decimal(str(self.price_tick))
        except Exception:
            _reject("risk_policy_invalid")
        if (
            not minimum.is_finite()
            or not maximum.is_finite()
            or not tick.is_finite()
            or minimum <= 0
            or maximum < minimum
            or tick <= 0
            or minimum % tick
            or maximum % tick
        ):
            _reject("risk_policy_invalid")
        object.__setattr__(self, "min_price", minimum)
        object.__setattr__(self, "max_price", maximum)
        object.__setattr__(self, "price_tick", tick)
        if (
            type(self.approval_key_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", self.approval_key_id)
            or isinstance(self.approval_ttl_seconds, bool)
            or type(self.approval_ttl_seconds) not in (int, float)
            or not math.isfinite(float(self.approval_ttl_seconds))
            or not 0 < float(self.approval_ttl_seconds) <= 60.0
        ):
            _reject("risk_policy_invalid")
        object.__setattr__(self, "approval_ttl_seconds", float(self.approval_ttl_seconds))


@dataclass(frozen=True)
class CtpSimNowManagedScopeSelection:
    """One immutable pair selection and exact run scope; not write authority."""

    execution_registration: CtpSimulationExecutionRegistration
    front_pair_selection: CtpFrontPairSelection
    front_pair_set_sha256: str
    config_digest: str
    effective_digest: str
    profile_digest: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.execution_registration) is not CtpSimulationExecutionRegistration:
            _reject("execution_registration_required")
        if type(self.front_pair_selection) is not CtpFrontPairSelection:
            _reject("front_pair_selection_required")
        if (
            self.execution_registration.front_pair_set_sha256 != self.front_pair_set_sha256
            or self.execution_registration.config_digest != self.config_digest
            or self.execution_registration.md_front != self.front_pair_selection.pair.md_front
            or self.execution_registration.td_front != self.front_pair_selection.pair.td_front
            or self.execution_registration.front_pair_set_sha256 is None
            or self.execution_registration.config_digest is None
            or self.execution_registration.effective_digest != self.effective_digest
            or self.execution_registration.profile_digest != self.profile_digest
        ):
            _reject("selected_scope_binding_mismatch")
        for value, name in (
            (self.front_pair_set_sha256, "front_pair_set_sha256"),
            (self.config_digest, "config_digest"),
            (self.effective_digest, "effective_digest"),
        ):
            if type(value) is not str or not _SHA256_RE.fullmatch(value):
                _reject("invalid_" + name)
        if self.profile_digest is not None and (
            type(self.profile_digest) is not str or not _SHA256_RE.fullmatch(self.profile_digest)
        ):
            _reject("invalid_profile_digest")


def _private_config(effective: EffectiveRuntimeConfig) -> CtpPrivateConfig:
    """Return the freshly sealed, canonical mode-neutral ``ctp:`` block."""

    private = getattr(effective.config, "ctp", None)
    if type(private) is not CtpPrivateConfig:
        _reject("sealed_canonical_ctp_private_config_required")
    # In simulation mode the legacy attribute is only a compatibility view.
    # It must refer to this exact parsed object and cannot supply an alternate
    # private block.
    legacy = getattr(effective.config, "ctp_simnow", None)
    if legacy is not None and legacy is not private:
        _reject("ctp_private_config_alias_mismatch")
    return private


def _verify_sealed_runtime(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    policy: CtpSimNowManagedExecutionPolicy,
) -> Tuple[EffectiveRuntimeConfig, CtpPrivateConfig]:
    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        if effective.registration is not policy.runtime_registration:
            _reject("runtime_registration_mismatch")
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
    except CtpSimNowManagedOperatorError:
        raise
    except (RuntimeConfigError, Exception):
        _reject("sealed_runtime_rejected")
    if (
        current.registration is not effective.registration
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
    ):
        _reject("sealed_runtime_config_changed")
    profile = _managed_selector_profile(current.registration, policy.allowed_secrets_ref)
    profile_shape = (
        current.profile is profile
        and profile is not None
        and profile.digest == current.profile.digest
    )
    legacy_shape = profile is None and current.profile is None
    if not (profile_shape or legacy_shape):
        _reject("effective_profile_mismatch")
    if (
        current.mode != "simulation"
        or current.preset != "sandbox"
        or current.config.secrets_ref != policy.allowed_secrets_ref
        or current.registration.runtime_id != policy.runtime_registration.runtime_id
        or current.config.strategy_id != policy.runtime_registration.strategy_id
        or current.policy.environment != "sandbox"
        or current.policy.mode != "simulation"
        or current.required_capabilities != _REQUIRED_CAPABILITIES
        or current.allows_production_writes is not False
        or current.allows_external_writes is not True
        or current.order_route != "managed_execution"
        or current.account_access != "sandbox_direct_provider"
        or current.requires_approval is not True
        or current.requires_live_confirmation is not False
    ):
        _reject("effective_policy_mismatch")
    private = _private_config(current)
    if (
        type(private.front_pairs) is not tuple
        or not 1 <= len(private.front_pairs) <= _MAX_FRONT_PAIRS
    ):
        _reject("config_contract_or_candidate_mismatch")
    if (
        type(private.instrument_id) is not str
        or not _INSTRUMENT_RE.fullmatch(private.instrument_id)
        or type(private.exchange_id) is not str
        or not _EXCHANGE_RE.fullmatch(private.exchange_id)
        or type(private.hedge_flag) is not str
        or private.hedge_flag not in ("1", "2", "3")
    ):
        _reject("config_contract_or_candidate_mismatch")
    # Validate the exact candidate set before probing. It remains sourced from
    # the sealed config; its digest is added to the invocation registration.
    ctp_simnow_front_pair_set_sha256(private.front_pairs)
    return current, private


def select_ctp_simnow_managed_scope(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    policy: CtpSimNowManagedExecutionPolicy,
    *,
    connector: Optional[Callable[[str, int, float], Any]] = None,
    process_factory: Optional[Callable[..., Any]] = None,
    clock: Optional[Callable[[], float]] = None,
    timeout_seconds: float = 3.0,
    repeated_samples: int = 3,
) -> CtpSimNowManagedScopeSelection:
    """Verify sealed SimNow scope, probe all candidates, and pin one run pair.

    Runtime, config contract, candidate, and hard risk checks precede probing.
    The account fingerprint, ordered candidate digest, contract scope, and
    measured pair are then bound into the invocation registration. Password,
    app ID, and auth code are never accessed; credentials and the SDK are not
    loaded here. Ties retain config order and no retry/reselection occurs after
    this immutable result is produced.
    """

    if type(policy) is not CtpSimNowManagedExecutionPolicy:
        _reject("code_owned_policy_required")
    current, private = _verify_sealed_runtime(effective, registry, policy)
    try:
        selection = select_ctp_front_pair(
            private.front_pairs,
            timeout_seconds=timeout_seconds,
            max_pairs=_MAX_FRONT_PAIRS,
            repeated_samples=repeated_samples,
            connector=connector,
            process_factory=process_factory,
            clock=clock,
        )
    except CtpFrontPairProbeError as exc:
        _reject("front_pair_probe_" + exc.reason)

    account_fingerprint = hashlib.sha256(
        f"{private.broker_id}:{private.user_id}".encode("utf-8")
    ).hexdigest()[:16]
    account_digest = hashlib.sha256(("acct_" + account_fingerprint).encode("ascii")).hexdigest()
    candidate_digest = ctp_simnow_front_pair_set_sha256(private.front_pairs)

    profile = current.profile
    try:
        registration = CtpSimulationExecutionRegistration(
            runtime_registration=policy.runtime_registration,
            environment=policy.environment,
            sdk_profile="config_front_pair",
            td_front=selection.pair.td_front,
            md_front=selection.pair.md_front,
            account_fingerprint_sha256=account_digest,
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
            config_digest=current.config.config_digest,
            effective_digest=current.effective_digest,
            profile_digest=None if profile is None else profile.digest,
            profile_approval_receipt_digest=(
                None if profile is None else profile.approval_receipt_digest
            ),
        )
        if profile is None:
            require_ctp_simulation_execution_admission(current, registry, registration)
        else:
            _verify_profile_selection_registration(
                current, registry, profile, registration, private
            )
    except CtpSimulationExecutionError as exc:
        _reject("execution_admission_" + exc.reason)
    except Exception:
        _reject("execution_admission_rejected")

    return CtpSimNowManagedScopeSelection(
        execution_registration=registration,
        front_pair_selection=selection,
        front_pair_set_sha256=candidate_digest,
        config_digest=current.config.config_digest,
        effective_digest=current.effective_digest,
        profile_digest=None if profile is None else profile.digest,
    )


def _verify_profile_selection_registration(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    profile: RuntimeProfile,
    registration: CtpSimulationExecutionRegistration,
    private: CtpPrivateConfig,
) -> None:
    """Bind this selector result to one sealed profile and its private CTP scope."""

    try:
        require_effective_runtime_config_seal(effective, registry)
    except Exception:
        _reject("sealed_runtime_rejected")
    account_fingerprint = hashlib.sha256(
        "{0}:{1}".format(private.broker_id, private.user_id).encode("utf-8")
    ).hexdigest()[:16]
    account_digest = hashlib.sha256(("acct_" + account_fingerprint).encode("ascii")).hexdigest()
    selected = effective.registration.profile_for("simulation", "sandbox")
    if (
        selected is not profile
        or effective.profile is not profile
        or profile.digest != registration.profile_digest
        or profile.approval_receipt_digest != registration.profile_approval_receipt_digest
        or profile.sandbox_write_policy != "receipt_required"
        or profile.available_capabilities != _REQUIRED_CAPABILITIES
        or profile.allowed_secrets_refs != (registration.allowed_secrets_ref,)
        or profile.allowed_parameter_keys != ()
        or profile.offline_managed_execution is not False
        or profile.approval_receipt_digest is None
        or effective.config.secrets_ref != registration.allowed_secrets_ref
        or effective.config.config_digest != registration.config_digest
        or effective.effective_digest != registration.effective_digest
        or effective.required_capabilities != _REQUIRED_CAPABILITIES
        or effective.allows_external_writes is not True
        or effective.allows_production_writes is not False
        or effective.requires_approval is not True
        or effective.order_route != "managed_execution"
        or effective.account_access != "sandbox_direct_provider"
        or registration.runtime_registration is not effective.registration
        or registration.account_fingerprint_sha256 != account_digest
        or registration.front_pair_set_sha256
        != ctp_simnow_front_pair_set_sha256(private.front_pairs)
        or registration.instrument_id != private.instrument_id
        or registration.exchange_id != private.exchange_id
        or registration.hedge_flag != private.hedge_flag
        or (registration.md_front, registration.td_front)
        not in tuple((pair["md_front"], pair["td_front"]) for pair in private.front_pairs)
    ):
        _reject("profile_selection_binding_mismatch")


__all__ = [
    "CtpSimNowManagedExecutionPolicy",
    "CtpSimNowManagedOperatorError",
    "CtpSimNowManagedScopeSelection",
    "ctp_simnow_front_pair_set_sha256",
    "select_ctp_simnow_managed_scope",
]
