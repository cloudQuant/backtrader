"""Config-driven front selection for a future managed CTP production writer.

This module stops at a non-authorizing execution-scope binding. It does not
resolve production credentials, verify the wheel pin or approval receipt,
import an SDK, create a provider session, or expose submit/cancel operations.
It is not registered in the default inventory or CLI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontPairEvidence,
    CtpFrontPairProbeError,
    CtpFrontPairSelection,
    select_ctp_front_pair,
)
from .ctp_production_execution_admission import (
    CtpProductionExecutionAdmissionError,
    CtpProductionExecutionConfigBinding,
    CtpProductionExecutionRegistration,
    require_ctp_production_execution_config_binding,
)
from .config import RuntimeConfig
from .registry import EffectiveRuntimeConfig, RegisteredRuntime, RuntimeRegistry


class CtpProductionManagedCompositionError(ValueError):
    """Redacted fail-closed rejection of production front composition."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> None:
    raise CtpProductionManagedCompositionError(reason) from None


@dataclass(frozen=True)
class CtpProductionManagedScopeSelection:
    """Transport-selected production scope; every operational authority is false."""

    binding: CtpProductionExecutionConfigBinding = field(repr=False)
    selected_front_index: int
    reachable_candidate_count: int
    latency_score_ms: float
    selected_front_sha256: str
    approval_receipt_verified: bool = field(default=False, init=False)
    artifact_verified: bool = field(default=False, init=False)
    credentials_resolved: bool = field(default=False, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.binding) is not CtpProductionExecutionConfigBinding:
            _reject("invalid_scope_binding")
        if (
            type(self.selected_front_index) is not int
            or self.selected_front_index < 0
            or type(self.reachable_candidate_count) is not int
            or self.reachable_candidate_count <= 0
            or type(self.latency_score_ms) not in (int, float)
            or not math.isfinite(self.latency_score_ms)
            or self.latency_score_ms < 0
            or self.binding.selected_front_index != self.selected_front_index
            or self.binding.front_pair_sha256 != self.selected_front_sha256
        ):
            _reject("invalid_selection_evidence")
        if any(
            value is not False
            for value in (
                self.approval_receipt_verified,
                self.artifact_verified,
                self.credentials_resolved,
                self.provider_access_authorized,
                self.execution_authorized,
                self.external_writes_authorized,
                self.order_submission_authorized,
                self.cancellation_authorized,
                self.arming_authorized,
            )
        ):
            _reject("authorizing_evidence_forbidden")

    def __bool__(self) -> bool:
        raise TypeError("production managed scope selection is non-authorizing evidence")

    def as_public_dict(self) -> dict[str, object]:
        return {
            "approval_receipt_verified": self.approval_receipt_verified,
            "artifact_verified": self.artifact_verified,
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "credentials_resolved": self.credentials_resolved,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "effective_digest": self.binding.effective_digest,
            "front_pair_set_sha256": self.binding.front_pair_set_sha256,
            "latency_score_ms": self.latency_score_ms,
            "order_submission_authorized": self.order_submission_authorized,
            "provider_access_authorized": self.provider_access_authorized,
            "reachable_candidate_count": self.reachable_candidate_count,
            "selected_front_index": self.selected_front_index,
            "selected_front_sha256": self.selected_front_sha256,
            "scope_identity_sha256": self.binding.scope_identity_sha256,
        }


def select_ctp_production_managed_config_scope(
    *,
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    effective_runtime: Optional[EffectiveRuntimeConfig] = None,
    timeout_seconds: float = 2.0,
    repeated_samples: int = 3,
) -> CtpProductionManagedScopeSelection:
    """Select a configured pair and bind its non-authorizing scope identity.

    A pinned legacy registration still checks its approved exact pair or
    candidate-set digest. A ``sealed_config`` registration derives candidates
    and contract scope from the canonical live ``ctp:`` block and requires the
    sealed effective runtime for the same config. Profile-backed scope is
    considered only when that exact live profile and effective runtime pass
    production admission before probing. The exact same effective object is
    checked again when rebinding the selected pair. No environment,
    time-based preset, or fallback endpoint is consulted.
    The return value is solely transport and scope identity evidence. It does
    not verify an approval receipt or make a receipt authorize this identity.
    A separate trusted approval service would need an explicit, non-circular
    mapping from a verified receipt digest to the returned scope identity.
    Artifact provenance, credentials, provider sessions, writer exclusion and
    order/cancel semantics remain outside this pure selector.
    """

    if type(admission_registration) is not CtpProductionExecutionRegistration:
        _reject("production_execution_config_rejected")
    runtime_registration = admission_registration.runtime_registration
    profile_backed_registration = type(runtime_registration) is RegisteredRuntime and bool(
        runtime_registration.profiles
    )
    profile_backed_effective = (
        type(effective_runtime) is EffectiveRuntimeConfig and effective_runtime.profile is not None
    )
    if profile_backed_registration or profile_backed_effective:
        reviewed_live_profile = (
            runtime_registration.profile_for("live", "managed_live_direct")
            if profile_backed_registration
            else None
        )
        if (
            not profile_backed_registration
            or not profile_backed_effective
            or reviewed_live_profile is None
            or effective_runtime.profile is not reviewed_live_profile
        ):
            _reject("profile_dispatch_unavailable")
    if admission_registration.scope_binding_mode == "sealed_config" and effective_runtime is None:
        _reject("sealed_effective_runtime_required")

    try:
        candidate_binding = require_ctp_production_execution_config_binding(
            config,
            registry,
            admission_registration,
            effective_runtime=effective_runtime,
        )
    except CtpProductionExecutionAdmissionError:
        _reject("production_execution_config_rejected")
    except Exception:
        _reject("production_execution_config_rejected")

    try:
        selection = select_ctp_front_pair(
            tuple(
                {"md_front": md_front, "td_front": td_front}
                for md_front, td_front in candidate_binding.front_pairs
            ),
            timeout_seconds=timeout_seconds,
            max_pairs=8,
            repeated_samples=repeated_samples,
        )
    except CtpFrontPairProbeError:
        _reject("configured_front_probe_rejected")
    except Exception:
        _reject("configured_front_probe_rejected")
    if (
        type(selection) is not CtpFrontPairSelection
        or type(selection.pair) is not CtpConfiguredFrontPair
    ):
        _reject("invalid_front_selection")
    if type(selection.evidence) is not tuple or any(
        type(item) is not CtpFrontPairEvidence for item in selection.evidence
    ):
        _reject("invalid_front_selection")
    selected_pair = (selection.pair.md_front, selection.pair.td_front)
    evidence_by_index = {
        item.config_index: item for item in selection.evidence if type(item.config_index) is int
    }
    if (
        type(selection.config_index) is not int
        or selection.config_index < 0
        or selection.config_index >= len(candidate_binding.front_pairs)
        or len(selection.evidence) != len(candidate_binding.front_pairs)
        or len(evidence_by_index) != len(candidate_binding.front_pairs)
        or candidate_binding.front_pairs[selection.config_index] != selected_pair
        or selection.config_index not in evidence_by_index
        or evidence_by_index[selection.config_index].pair != selection.pair
        or evidence_by_index[selection.config_index].reachable is not True
        or evidence_by_index[selection.config_index].latency_score_ms != selection.latency_score_ms
        or type(selection.latency_score_ms) not in (int, float)
        or not math.isfinite(selection.latency_score_ms)
        or selection.latency_score_ms < 0
        or sum(1 for item in selection.evidence if item.reachable) < 1
    ):
        _reject("front_selection_outside_config")
    try:
        binding = require_ctp_production_execution_config_binding(
            config,
            registry,
            admission_registration,
            selected_front_pair=selected_pair,
            effective_runtime=effective_runtime,
        )
    except CtpProductionExecutionAdmissionError:
        _reject("selected_front_not_approved")
    except Exception:
        _reject("selected_front_not_approved")
    if (
        binding.selected_front_index != selection.config_index
        or binding.md_front != selected_pair[0]
        or binding.td_front != selected_pair[1]
    ):
        _reject("selected_front_binding_changed")
    return CtpProductionManagedScopeSelection(
        binding=binding,
        selected_front_index=selection.config_index,
        reachable_candidate_count=sum(1 for item in selection.evidence if item.reachable),
        latency_score_ms=selection.latency_score_ms,
        selected_front_sha256=binding.front_pair_sha256,
    )


__all__ = [
    "CtpProductionManagedCompositionError",
    "CtpProductionManagedScopeSelection",
    "select_ctp_production_managed_config_scope",
]
