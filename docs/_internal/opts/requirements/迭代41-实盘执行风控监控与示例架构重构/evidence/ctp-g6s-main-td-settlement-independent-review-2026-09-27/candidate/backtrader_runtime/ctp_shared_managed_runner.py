"""Shared, non-authorizing preparation path for a future managed CTP runner.

Both supported modes enter through :func:`prepare_shared_ctp_managed_runner`.
The sealed runtime config selects the mode; the caller cannot override it.
The shared path first requires a reviewed two-profile grant for the same
code-owned runner, then delegates to a mode-specific typed admission adapter,
and finally binds that adapter's exact selected MD/TD pair back to the current
canonical ``ctp:`` config through :mod:`ctp_mode_scope`.

This is deliberately a preparation seam, not a dispatchable writer. The
SimNow adapter returns the existing simulation execution registration; the
production adapter returns the existing non-authorizing production scope.
No SDK, credential resolver, native client, execution session, or persistent
writer is created here. Some contracts can be shared now: sealed config and
profile identity, exact front-pair selection, scope binding, generic managed
order/action request shapes, and Store/Broker projection interfaces. The
current durable CTP action journal and native-session owner are still the
SimNow implementation (including its ``simnow`` environment and
``ctp_simnow_execution`` state-root assumptions). Production has no matching
SDK client/session or durable action-journal implementation yet, so this
module does not claim those components are already shared.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import weakref
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, Optional, Tuple, Union

from .config import CtpPrivateConfig
from .ctp_mode_scope import (
    CtpModeScopeBinding,
    CtpModeScopeError,
    _front_pair_set_sha256,
    _selected_front_pair_sha256,
    bind_ctp_mode_scope,
    require_ctp_mode_scope_binding,
)
from .ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from .ctp_production_execution_admission import (
    CtpProductionExecutionRegistration,
    _require_registration_seal as _require_production_registration_seal,
    production_front_pair_set_sha256,
)
from .ctp_production_managed_composition import (
    CtpProductionManagedScopeSelection,
    select_ctp_production_managed_config_scope,
)
from .ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    CtpSimNowManagedScopeSelection,
    ctp_simnow_front_pair_set_sha256,
    select_ctp_simnow_managed_scope,
)
from .ctp_simulation_execution import CtpSimulationExecutionRegistration
from .policy import MANAGED_WRITE_CAPABILITIES
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


_SIMULATION = ("simulation", "sandbox")
_PRODUCTION = ("live", "managed_live_direct")
_SUPPORTED_MODE_PRESETS = frozenset((_SIMULATION, _PRODUCTION))
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PLAN_DOMAIN = b"backtrader-shared-managed-ctp-runner-plan-v1\0"
_PLAN_SEALS: Dict[int, Tuple[Any, str, Any, Any, Any]] = {}


class CtpSharedManagedRunnerError(ValueError):
    """Redacted rejection from shared managed CTP preparation."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpSharedManagedRunnerError(reason) from None


@dataclass(frozen=True, repr=False)
class CtpSimNowManagedRunnerAdapter:
    """Strongly typed SimNow selector and risk-policy adapter.

    The wrapped selector validates the sandbox receipt-required profile and
    code-owned SimNow risk policy before its credential-free configured-front
    probe. The adapter never resolves private credentials or creates a client.
    """

    policy: CtpSimNowManagedExecutionPolicy = field(repr=False)
    connector: Optional[Callable[[str, int, float], Any]] = field(
        default=None, repr=False, compare=False
    )
    process_factory: Optional[Callable[..., Any]] = field(default=None, repr=False, compare=False)
    clock: Optional[Callable[[], float]] = field(default=None, repr=False, compare=False)
    timeout_seconds: float = 3.0
    repeated_samples: int = 3

    def select_and_admit(
        self, effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
    ) -> CtpSimNowManagedScopeSelection:
        if type(self.policy) is not CtpSimNowManagedExecutionPolicy:
            _reject("simnow_mode_policy_required")
        if self.policy.runtime_registration is not effective.registration:
            _reject("simnow_registration_mismatch")
        try:
            return select_ctp_simnow_managed_scope(
                effective,
                registry,
                self.policy,
                connector=self.connector,
                process_factory=self.process_factory,
                clock=self.clock,
                timeout_seconds=self.timeout_seconds,
                repeated_samples=self.repeated_samples,
            )
        except Exception as exc:
            if isinstance(exc, CtpSharedManagedRunnerError):
                raise
            reason = getattr(exc, "reason", None)
            if type(reason) is str and re.fullmatch(r"[a-z0-9_]{1,96}", reason):
                _reject("simnow_admission_" + reason)
            _reject("simnow_admission_rejected")


@dataclass(frozen=True, repr=False)
class CtpProductionManagedRunnerAdapter:
    """Strongly typed live config/risk binding adapter.

    This adapter can currently select and bind production scope only. The
    production receipt and artifact digests are identities on the code-owned
    registration here; this path does not verify a receipt signature or wheel
    provenance. The production composition module has no native writer/session
    implementation to invoke after this result is prepared.
    """

    registration: CtpProductionExecutionRegistration = field(repr=False)
    timeout_seconds: float = 2.0
    repeated_samples: int = 3

    def select_and_admit(
        self, effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
    ) -> CtpProductionManagedScopeSelection:
        if type(self.registration) is not CtpProductionExecutionRegistration:
            _reject("production_admission_registration_required")
        if self.registration.runtime_registration is not effective.registration:
            _reject("production_registration_mismatch")
        try:
            return select_ctp_production_managed_config_scope(
                config=effective.config,
                registry=registry,
                admission_registration=self.registration,
                effective_runtime=effective,
                timeout_seconds=self.timeout_seconds,
                repeated_samples=self.repeated_samples,
            )
        except Exception as exc:
            if isinstance(exc, CtpSharedManagedRunnerError):
                raise
            reason = getattr(exc, "reason", None)
            if type(reason) is str and re.fullmatch(r"[a-z0-9_]{1,96}", reason):
                _reject("production_admission_" + reason)
            _reject("production_admission_rejected")


ModeAdmission = Union[CtpSimNowManagedScopeSelection, CtpProductionManagedScopeSelection]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _mode_profile_grants(profile: Any, expected: Tuple[str, str]) -> bool:
    if type(profile) is not RuntimeProfile:
        return False
    mode, preset = expected
    expected_write_policy = "receipt_required" if expected == _SIMULATION else "deny"
    return (
        profile.mode == mode
        and profile.preset == preset
        and profile.allowed_parameter_keys == ()
        and profile.allowed_secrets_refs == ("config_yaml",)
        and profile.available_capabilities == MANAGED_WRITE_CAPABILITIES
        and profile.capability_modules == ()
        and profile.offline_managed_execution is False
        and profile.sandbox_write_policy == expected_write_policy
        and type(profile.approval_receipt_digest) is str
        and _DIGEST_RE.fullmatch(profile.approval_receipt_digest) is not None
        and type(profile.runner_module) is str
        and bool(profile.runner_module)
        and type(profile.runner_entrypoint) is str
        and bool(profile.runner_entrypoint)
    )


def _require_current_effective_runtime_config(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> EffectiveRuntimeConfig:
    """Reload the registered config and reject a stale in-memory seal.

    ``require_effective_runtime_config_seal`` proves resolver provenance and
    object integrity; it deliberately does not reread ``config.yaml``. Shared
    CTP mode selection and the post-probe/session gates need both properties.
    Re-resolving here also picks up private credential rotation for downstream
    code while the public config/effective digests continue to exclude secrets.
    """

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
    except Exception:
        _reject("shared_runner_config_reseal_rejected")
    if (
        current.registration is not effective.registration
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
        or current.mode != effective.mode
        or current.preset != effective.preset
        or current.profile is not effective.profile
        or current.config.secrets_ref != effective.config.secrets_ref
    ):
        _reject("shared_runner_config_stale")
    return current


def _require_shared_runner_contract(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> Tuple[RegisteredRuntime, RuntimeProfile]:
    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_runtime_required")
    if registry.trusted is not True:
        _reject("trusted_registry_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        registration = registry.require_runtime_dir(effective.config.strategy_dir)
    except Exception:
        _reject("sealed_runtime_rejected")
    if type(registration) is not RegisteredRuntime or registration is not effective.registration:
        _reject("runtime_registration_mismatch")
    mode_preset = (effective.mode, effective.preset)
    if mode_preset not in _SUPPORTED_MODE_PRESETS:
        _reject("unsupported_mode_preset")

    simulation = registration.profile_for(*_SIMULATION)
    production = registration.profile_for(*_PRODUCTION)
    if not _mode_profile_grants(simulation, _SIMULATION) or not _mode_profile_grants(
        production, _PRODUCTION
    ):
        _reject("shared_runner_profile_grant_missing")
    if (
        simulation.runner_module != production.runner_module
        or simulation.runner_entrypoint != production.runner_entrypoint
    ):
        _reject("shared_runner_identity_mismatch")

    selected_profile = simulation if mode_preset == _SIMULATION else production
    if effective.profile is not selected_profile:
        _reject("effective_profile_mismatch")
    if (
        registration.strategy_id != effective.config.strategy_id
        or registration.allowed_presets != ()
        or registration.allowed_parameter_keys != ()
        or registration.allowed_secrets_refs != ("none",)
        or registration.available_capabilities != ()
        or registration.capability_modules != ()
        or registration.offline_managed_execution is not False
        or registration.sandbox_write_policy != "deny"
        or registration.approval_receipt_digest is not None
        or registration.runner_module is not None
    ):
        _reject("shared_runner_legacy_registration_not_inert")
    config = effective.config
    private = getattr(config, "ctp", None)
    legacy = getattr(config, "ctp_simnow", None)
    if (
        type(private) is not CtpPrivateConfig
        or getattr(config, "ctp_production", None) is not None
        or (legacy is not None and legacy is not private)
        or config.secrets_ref != "config_yaml"
        or tuple(config.parameters) != ()
    ):
        _reject("canonical_ctp_runtime_required")
    return registration, selected_profile


def _front_selection_facts(selection: Any) -> Dict[str, Any]:
    if (
        type(selection) is not CtpFrontPairSelection
        or type(selection.pair) is not CtpConfiguredFrontPair
        or type(selection.evidence) is not tuple
        or not 1 <= len(selection.evidence) <= 8
        or type(selection.config_index) is not int
        or not 0 <= selection.config_index < len(selection.evidence)
        or type(selection.latency_score_ms) not in (int, float)
        or not math.isfinite(selection.latency_score_ms)
        or selection.latency_score_ms < 0
        or type(selection.timeout_seconds) not in (int, float)
        or not math.isfinite(selection.timeout_seconds)
        or selection.timeout_seconds <= 0
        or type(selection.repeated_samples) is not int
        or selection.repeated_samples <= 0
    ):
        _reject("front_selection_binding_invalid")
    evidence_facts = []
    seen_indexes = set()
    for item in selection.evidence:
        if (
            type(item) is not CtpFrontPairEvidence
            or type(item.pair) is not CtpConfiguredFrontPair
            or type(item.config_index) is not int
            or not 0 <= item.config_index < len(selection.evidence)
            or type(item.reachable) is not bool
            or type(item.md) is not CtpFrontEndpointEvidence
            or type(item.td) is not CtpFrontEndpointEvidence
            or item.md.front != item.pair.md_front
            or item.td.front != item.pair.td_front
            or type(item.md.samples) is not tuple
            or type(item.td.samples) is not tuple
        ):
            _reject("front_selection_binding_invalid")
        for endpoint in (item.md, item.td):
            for sample in endpoint.samples:
                if type(sample) is not CtpFrontProbeSample:
                    _reject("front_selection_binding_invalid")
        if item.config_index in seen_indexes:
            _reject("front_selection_binding_invalid")
        seen_indexes.add(item.config_index)
        evidence_facts.append(
            {
                "config_index": item.config_index,
                "latency_score_ms": item.latency_score_ms,
                "md_front": item.pair.md_front,
                "md_samples": tuple(
                    (
                        sample.connected,
                        sample.latency_ms,
                        sample.failure,
                        sample.dns_resolution_ms,
                        sample.tcp_connect_ms,
                    )
                    for sample in item.md.samples
                ),
                "reachable": item.reachable,
                "td_front": item.pair.td_front,
                "td_samples": tuple(
                    (
                        sample.connected,
                        sample.latency_ms,
                        sample.failure,
                        sample.dns_resolution_ms,
                        sample.tcp_connect_ms,
                    )
                    for sample in item.td.samples
                ),
            }
        )
    evidence_facts.sort(key=lambda fact: fact["config_index"])
    if (
        tuple(item["config_index"] for item in evidence_facts) != tuple(range(len(evidence_facts)))
        or (
            evidence_facts[selection.config_index]["md_front"],
            evidence_facts[selection.config_index]["td_front"],
        )
        != (selection.pair.md_front, selection.pair.td_front)
        or evidence_facts[selection.config_index]["reachable"] is not True
        or evidence_facts[selection.config_index]["latency_score_ms"] != selection.latency_score_ms
        or sum(bool(item["reachable"]) for item in evidence_facts) < 1
    ):
        _reject("front_selection_binding_invalid")
    return {
        "config_index": selection.config_index,
        "evidence": tuple(evidence_facts),
        "latency_score_ms": selection.latency_score_ms,
        "md_front": selection.pair.md_front,
        "repeated_samples": selection.repeated_samples,
        "td_front": selection.pair.td_front,
        "timeout_seconds": selection.timeout_seconds,
    }


def _safe_fact(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int, float):
        return value
    if type(value) is Decimal:
        return str(value)
    if type(value) in (tuple, list):
        return tuple(_safe_fact(item) for item in value)
    if type(value) is dict:
        return {str(key): _safe_fact(item) for key, item in sorted(value.items())}
    _reject("mode_admission_binding_invalid")


def _runtime_profile_for_scope(
    scope: CtpModeScopeBinding, runtime_registration: Any
) -> RuntimeProfile:
    if (
        type(runtime_registration) is not RegisteredRuntime
        or runtime_registration.digest != scope.registration_digest
        or runtime_registration.runtime_id != scope.runtime_id
        or runtime_registration.strategy_id != scope.strategy_id
    ):
        _reject("mode_admission_runtime_mismatch")
    simulation = runtime_registration.profile_for(*_SIMULATION)
    production = runtime_registration.profile_for(*_PRODUCTION)
    if not _mode_profile_grants(simulation, _SIMULATION) or not _mode_profile_grants(
        production, _PRODUCTION
    ):
        _reject("mode_admission_profile_grant_missing")
    if (
        simulation.runner_module != production.runner_module
        or simulation.runner_entrypoint != production.runner_entrypoint
    ):
        _reject("mode_admission_runner_mismatch")
    mode_preset = (scope.mode, scope.preset)
    profile = simulation if mode_preset == _SIMULATION else production
    if (
        mode_preset not in _SUPPORTED_MODE_PRESETS
        or profile.digest != scope.profile_digest
        or profile.approval_receipt_digest != scope.profile_approval_receipt_digest
        or profile.runner_module != scope.runner_module
        or profile.runner_entrypoint != scope.runner_entrypoint
    ):
        _reject("mode_admission_profile_mismatch")
    return profile


def _validate_simnow_admission(
    scope: CtpModeScopeBinding,
    admission: CtpSimNowManagedScopeSelection,
    mode_registration: CtpSimulationExecutionRegistration,
) -> Tuple[Tuple[str, str, str, str], Dict[str, Any]]:
    if (
        scope.mode != _SIMULATION[0]
        or scope.preset != _SIMULATION[1]
        or type(admission) is not CtpSimNowManagedScopeSelection
        or type(mode_registration) is not CtpSimulationExecutionRegistration
        or admission.execution_registration is not mode_registration
    ):
        _reject("simnow_admission_type_or_mode_mismatch")
    try:
        CtpSimulationExecutionRegistration.__post_init__(mode_registration)
        CtpSimNowManagedScopeSelection.__post_init__(admission)
    except Exception:
        _reject("simnow_admission_binding_invalid")

    profile = _runtime_profile_for_scope(scope, mode_registration.runtime_registration)
    facts = _front_selection_facts(admission.front_pair_selection)
    pair = (facts["md_front"], facts["td_front"])
    candidate_pairs = tuple((fact["md_front"], fact["td_front"]) for fact in facts["evidence"])
    if (
        len(set(candidate_pairs)) != len(candidate_pairs)
        or pair != scope.selected_front_pair
        or pair != (mode_registration.md_front, mode_registration.td_front)
        or _front_pair_set_sha256(candidate_pairs) != scope.front_pair_set_sha256
        or ctp_simnow_front_pair_set_sha256(
            tuple({"md_front": md, "td_front": td} for md, td in candidate_pairs)
        )
        != admission.front_pair_set_sha256
        or admission.front_pair_set_sha256 != mode_registration.front_pair_set_sha256
        or admission.config_digest != scope.config_digest
        or admission.effective_digest != scope.effective_digest
        or mode_registration.config_digest != scope.config_digest
        or mode_registration.effective_digest != scope.effective_digest
        or mode_registration.profile_digest != profile.digest
        or mode_registration.profile_approval_receipt_digest != profile.approval_receipt_digest
        or mode_registration.profile_digest != scope.profile_digest
        or mode_registration.profile_approval_receipt_digest
        != scope.profile_approval_receipt_digest
        or mode_registration.instrument_id != scope.instrument_id
        or mode_registration.exchange_id != scope.exchange_id
        or mode_registration.hedge_flag != scope.hedge_flag
        or _selected_front_pair_sha256(pair) != scope.selected_front_pair_sha256
    ):
        _reject("simnow_admission_scope_mismatch")
    identity = (
        mode_registration.digest,
        admission.config_digest,
        admission.effective_digest,
        admission.profile_digest or "",
    )
    detail = {
        "kind": "simnow",
        "registration_digest": mode_registration.digest,
        "front_selection": facts,
        "front_pair_set_sha256": admission.front_pair_set_sha256,
        "profile_approval_receipt_digest": mode_registration.profile_approval_receipt_digest,
    }
    return identity, detail


def _validate_production_admission(
    scope: CtpModeScopeBinding,
    admission: CtpProductionManagedScopeSelection,
    mode_registration: CtpProductionExecutionRegistration,
) -> Tuple[Tuple[str, str, str, str], Dict[str, Any]]:
    if (
        scope.mode != _PRODUCTION[0]
        or scope.preset != _PRODUCTION[1]
        or type(admission) is not CtpProductionManagedScopeSelection
        or type(mode_registration) is not CtpProductionExecutionRegistration
    ):
        _reject("production_admission_type_or_mode_mismatch")
    try:
        _require_production_registration_seal(mode_registration)
    except Exception:
        _reject("production_admission_registration_invalid")
    runtime_registration = mode_registration.runtime_registration
    profile = _runtime_profile_for_scope(scope, runtime_registration)
    binding = admission.binding
    if type(binding.md_front) is not str or type(binding.td_front) is not str:
        _reject("production_selected_pair_missing")
    pair = (binding.md_front, binding.td_front)
    candidate_pairs = binding.front_pairs
    expected_registration_values = (
        ("environment", mode_registration.environment),
        ("registration_digest", mode_registration.digest),
        ("approval_receipt_id", mode_registration.approval_receipt_id),
        ("approval_receipt_sha256", mode_registration.approval_receipt_sha256),
        ("artifact_id", mode_registration.artifact_id),
        ("artifact_sha256", mode_registration.artifact_sha256),
        ("allowed_sides", mode_registration.allowed_sides),
        ("allowed_offsets", mode_registration.allowed_offsets),
        ("quantity_step", mode_registration.quantity_step),
        ("max_order_quantity", mode_registration.max_order_quantity),
        ("max_gross_position", mode_registration.max_gross_position),
        ("min_price", mode_registration.min_price),
        ("max_price", mode_registration.max_price),
        ("price_tick", mode_registration.price_tick),
        ("max_order_notional", mode_registration.max_order_notional),
    )
    if (
        type(candidate_pairs) is not tuple
        or not 1 <= len(candidate_pairs) <= 8
        or any(type(candidate) is not tuple or len(candidate) != 2 for candidate in candidate_pairs)
        or len(set(candidate_pairs)) != len(candidate_pairs)
        or type(admission.selected_front_index) is not int
        or not 0 <= admission.selected_front_index < len(candidate_pairs)
        or candidate_pairs[admission.selected_front_index] != pair
        or pair != scope.selected_front_pair
        or _front_pair_set_sha256(candidate_pairs) != scope.front_pair_set_sha256
        or production_front_pair_set_sha256(candidate_pairs) != binding.front_pair_set_sha256
        or admission.selected_front_sha256 != binding.front_pair_sha256
        or binding.selected_front_index != admission.selected_front_index
        or binding.runtime_registration_digest != scope.registration_digest
        or binding.runtime_id != scope.runtime_id
        or binding.strategy_id != scope.strategy_id
        or binding.config_digest != scope.config_digest
        or binding.effective_digest != scope.effective_digest
        or binding.instrument_id != scope.instrument_id
        or binding.exchange_id != scope.exchange_id
        or binding.hedge_flag != scope.hedge_flag
        or mode_registration.approval_receipt_sha256 != profile.approval_receipt_digest
        or _selected_front_pair_sha256(pair) != scope.selected_front_pair_sha256
        or any(
            getattr(binding, name) != expected for name, expected in expected_registration_values
        )
        or type(admission.reachable_candidate_count) is not int
        or not 1 <= admission.reachable_candidate_count <= len(candidate_pairs)
        or type(admission.latency_score_ms) not in (int, float)
        or not math.isfinite(admission.latency_score_ms)
        or admission.latency_score_ms < 0
        or any(
            getattr(binding, name) is not False
            for name in (
                "provider_access_authorized",
                "credential_access_authorized",
                "execution_authorized",
                "external_writes_authorized",
                "order_submission_authorized",
                "cancellation_authorized",
                "arming_authorized",
            )
        )
    ):
        _reject("production_admission_scope_mismatch")
    identity = (
        mode_registration.digest,
        binding.config_digest,
        binding.effective_digest or "",
        scope.profile_digest,
    )
    detail = {
        "kind": "production",
        "mode_registration_digest": mode_registration.digest,
        "selection": {
            "selected_front_index": admission.selected_front_index,
            "reachable_candidate_count": admission.reachable_candidate_count,
            "latency_score_ms": admission.latency_score_ms,
            "selected_front_sha256": admission.selected_front_sha256,
        },
        "binding": {key: _safe_fact(value) for key, value in vars(binding).items()},
    }
    return identity, detail


def _validate_plan_admission(
    scope: CtpModeScopeBinding,
    admission: ModeAdmission,
    mode_registration: Union[
        CtpSimulationExecutionRegistration, CtpProductionExecutionRegistration
    ],
) -> Tuple[Tuple[str, str, str, str], str]:
    if type(admission) is CtpSimNowManagedScopeSelection:
        identity, detail = _validate_simnow_admission(scope, admission, mode_registration)
    elif type(admission) is CtpProductionManagedScopeSelection:
        identity, detail = _validate_production_admission(scope, admission, mode_registration)
    else:
        _reject("mode_admission_result_invalid")
    if (
        identity[0] == ""
        or not _DIGEST_RE.fullmatch(identity[0])
        or identity[1] != scope.config_digest
        or identity[2] != scope.effective_digest
        or identity[3] != scope.profile_digest
    ):
        _reject("mode_admission_identity_mismatch")
    return identity, hashlib.sha256(_canonical(detail)).hexdigest()


def _plan_digest(plan: "CtpSharedManagedRunnerPlan") -> str:
    identity, admission_facts_digest = _validate_plan_admission(
        plan.scope, plan.admission, plan.mode_admission_registration
    )
    if plan.admission_identity != identity:
        _reject("shared_runner_plan_cached_identity_mismatch")
    return hashlib.sha256(
        _PLAN_DOMAIN
        + _canonical(
            {
                "admission_facts_digest": admission_facts_digest,
                "admission_identity": identity,
                "authority_facts": {
                    "cancellation_authorized": plan.cancellation_authorized,
                    "credentials_resolved": plan.credentials_resolved,
                    "execution_authorized": plan.execution_authorized,
                    "order_submission_authorized": plan.order_submission_authorized,
                    "provider_access_authorized": plan.provider_access_authorized,
                },
                "mode": plan.scope.mode,
                "plan_runner_module": plan.runner_module,
                "plan_runner_entrypoint": plan.runner_entrypoint,
                "scope_digest": plan.scope.scope_digest,
                "selected_front_pair_sha256": plan.scope.selected_front_pair_sha256,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class CtpSharedManagedRunnerPlan:
    """Mode-selected, pair-bound preparation result with no write authority."""

    scope: CtpModeScopeBinding = field(repr=False)
    admission: ModeAdmission = field(repr=False)
    mode_admission_registration: Union[
        CtpSimulationExecutionRegistration, CtpProductionExecutionRegistration
    ] = field(repr=False)
    runner_module: str
    runner_entrypoint: str
    admission_identity: Tuple[str, str, str, str] = field(init=False, repr=False)
    provider_access_authorized: bool = field(default=False, init=False)
    credentials_resolved: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    _digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        require_ctp_mode_scope_binding(self.scope)
        if type(self.runner_module) is not str or not self.runner_module:
            _reject("shared_runner_identity_mismatch")
        if type(self.runner_entrypoint) is not str or not self.runner_entrypoint:
            _reject("shared_runner_identity_mismatch")
        if (
            self.scope.runner_module != self.runner_module
            or self.scope.runner_entrypoint != self.runner_entrypoint
        ):
            _reject("shared_runner_identity_mismatch")
        identity, _ = _validate_plan_admission(
            self.scope, self.admission, self.mode_admission_registration
        )
        object.__setattr__(self, "admission_identity", identity)
        if any(
            value is not False
            for value in (
                self.provider_access_authorized,
                self.credentials_resolved,
                self.execution_authorized,
                self.order_submission_authorized,
                self.cancellation_authorized,
            )
        ):
            _reject("authorizing_evidence_forbidden")
        digest = _plan_digest(self)
        object.__setattr__(self, "_digest", digest)
        _seal_plan(self, digest, self.admission, self.mode_admission_registration, self.scope)

    def __bool__(self) -> bool:
        raise TypeError("shared CTP runner plan is non-authorizing evidence")

    def as_public_dict(self) -> Dict[str, Any]:
        return {
            "admission_digest": hashlib.sha256(_canonical(self.admission_identity)).hexdigest(),
            "cancellation_authorized": False,
            "config_digest": self.scope.config_digest,
            "credentials_resolved": False,
            "effective_digest": self.scope.effective_digest,
            "execution_authorized": False,
            "mode": self.scope.mode,
            "order_submission_authorized": False,
            "preset": self.scope.preset,
            "profile_digest": self.scope.profile_digest,
            "provider_access_authorized": False,
            "runner_entrypoint": self.runner_entrypoint,
            "runner_module": self.runner_module,
            "runtime_id": self.scope.runtime_id,
            "selected_front_pair_sha256": self.scope.selected_front_pair_sha256,
        }


def _seal_plan(
    plan: CtpSharedManagedRunnerPlan,
    digest: str,
    admission: Any,
    mode_admission_registration: Any,
    scope: CtpModeScopeBinding,
) -> None:
    identifier = id(plan)

    def discard(reference: Any) -> None:
        current = _PLAN_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _PLAN_SEALS.pop(identifier, None)

    reference = weakref.ref(plan, discard)
    _PLAN_SEALS[identifier] = (
        reference,
        digest,
        weakref.ref(admission),
        weakref.ref(mode_admission_registration),
        weakref.ref(scope),
    )


def require_shared_managed_runner_plan(plan: CtpSharedManagedRunnerPlan) -> None:
    """Check issued-object integrity without rereading the current config.

    This is not a dispatch freshness check. A caller preparing to dispatch
    must call :func:`require_fresh_shared_managed_runner_plan` with the current
    sealed effective runtime and registry immediately before dispatch.
    """

    if type(plan) is not CtpSharedManagedRunnerPlan:
        _reject("shared_runner_plan_required")
    current = _PLAN_SEALS.get(id(plan))
    if current is None or current[0]() is not plan:
        _reject("shared_runner_plan_provenance_invalid")
    if (
        current[2]() is not plan.admission
        or current[3]() is not plan.mode_admission_registration
        or current[4]() is not plan.scope
    ):
        _reject("shared_runner_plan_provenance_invalid")
    try:
        require_ctp_mode_scope_binding(plan.scope)
        actual = _plan_digest(plan)
    except Exception:
        _reject("shared_runner_plan_provenance_invalid")
    if actual != current[1] or plan._digest != current[1]:
        _reject("shared_runner_plan_provenance_invalid")


def require_fresh_shared_managed_runner_plan(
    plan: CtpSharedManagedRunnerPlan,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> None:
    """Re-seal current disk config and require exact plan-scope identity.

    This offline gate must be repeated immediately before any future native
    session or write dispatch. It detects a config edit, mode change, profile
    change, runtime replacement, or selected-pair change after plan issuance.
    It never probes fronts, reads credentials, imports the SDK, or opens a
    session.
    """

    require_shared_managed_runner_plan(plan)
    try:
        effective = _require_current_effective_runtime_config(effective, registry)
        registration, profile = _require_shared_runner_contract(effective, registry)
        if (
            registration.digest != plan.scope.registration_digest
            or profile.digest != plan.scope.profile_digest
            or (effective.mode, effective.preset) != (plan.scope.mode, plan.scope.preset)
        ):
            _reject("shared_runner_plan_stale")
        fresh_scope = bind_ctp_mode_scope(
            effective,
            registry,
            selected_front_pair=plan.scope.selected_front_pair,
        )
    except CtpSharedManagedRunnerError:
        raise
    except Exception:
        _reject("shared_runner_plan_stale")
    if fresh_scope.scope_digest != plan.scope.scope_digest:
        _reject("shared_runner_plan_stale")


def prepare_shared_ctp_managed_runner(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    simnow_adapter: Optional[CtpSimNowManagedRunnerAdapter] = None,
    production_adapter: Optional[CtpProductionManagedRunnerAdapter] = None,
) -> CtpSharedManagedRunnerPlan:
    """Prepare one mode-specific admission through the shared runner path.

    Mode is derived exclusively from the sealed ``effective`` runtime. Both
    grants and the common runner identity are checked before invoking either
    mode adapter, so missing or unavailable profiles fail before front probes,
    credential access, SDK imports, or client/session construction.
    """

    try:
        effective = _require_current_effective_runtime_config(effective, registry)
        registration, profile = _require_shared_runner_contract(effective, registry)
    except CtpSharedManagedRunnerError:
        raise
    except Exception:
        _reject("shared_runner_contract_rejected")

    if (effective.mode, effective.preset) == _SIMULATION:
        if type(simnow_adapter) is not CtpSimNowManagedRunnerAdapter:
            _reject("simnow_mode_adapter_required")
        if type(simnow_adapter.policy) is not CtpSimNowManagedExecutionPolicy:
            _reject("simnow_mode_policy_required")
        if simnow_adapter.policy.runtime_registration is not registration:
            _reject("simnow_registration_mismatch")
        adapter = simnow_adapter
    else:
        if type(production_adapter) is not CtpProductionManagedRunnerAdapter:
            _reject("production_mode_adapter_required")
        if type(production_adapter.registration) is not CtpProductionExecutionRegistration:
            _reject("production_admission_registration_required")
        if production_adapter.registration.runtime_registration is not registration:
            _reject("production_registration_mismatch")
        adapter = production_adapter

    try:
        admission = adapter.select_and_admit(effective, registry)
        if type(admission) is CtpSimNowManagedScopeSelection:
            pair = (
                admission.front_pair_selection.pair.md_front,
                admission.front_pair_selection.pair.td_front,
            )
            mode_admission_registration = admission.execution_registration
        elif type(admission) is CtpProductionManagedScopeSelection:
            pair = (admission.binding.md_front, admission.binding.td_front)
            mode_admission_registration = adapter.registration
        else:
            _reject("mode_admission_result_invalid")
        scope = bind_ctp_mode_scope(effective, registry, selected_front_pair=pair)
        plan = CtpSharedManagedRunnerPlan(
            scope=scope,
            admission=admission,
            mode_admission_registration=mode_admission_registration,
            runner_module=profile.runner_module or "",
            runner_entrypoint=profile.runner_entrypoint,
        )
        require_fresh_shared_managed_runner_plan(plan, effective, registry)
        return plan
    except CtpSharedManagedRunnerError:
        raise
    except CtpModeScopeError as exc:
        reason = exc.reason
        if re.fullmatch(r"[a-z0-9_]{1,96}", reason):
            _reject("shared_scope_" + reason)
        _reject("shared_scope_rejected")
    except Exception:
        _reject("shared_runner_preparation_rejected")


__all__ = [
    "CtpProductionManagedRunnerAdapter",
    "CtpSharedManagedRunnerPlan",
    "CtpSharedManagedRunnerError",
    "CtpSimNowManagedRunnerAdapter",
    "prepare_shared_ctp_managed_runner",
    "require_fresh_shared_managed_runner_plan",
    "require_shared_managed_runner_plan",
]
