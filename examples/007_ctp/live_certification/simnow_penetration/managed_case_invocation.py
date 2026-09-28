"""Bind a validated 007 case scope to one immutable selected run identity.

This is offline provenance plumbing only. It does not authenticate a front
probe, own a lease, open a provider session, authorize dispatch, or certify a
case. Callers must supply the already sealed runtime/config objects they
validated for the invocation. Caller-supplied lease snapshots are rejected
until this offline binder has a trusted current lease-owner verifier; issued
bindings therefore carry no verified lease generation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from statistics import median
import weakref
from dataclasses import dataclass, field
from typing import Any, NoReturn, Optional

from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from backtrader_runtime.ctp_simnow_managed_md_bridge import ManagedCtpMdLeaseSnapshot
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedScopeSelection,
    _private_config,
    ctp_simnow_front_pair_set_sha256,
)
from backtrader_runtime.ctp_simulation_execution import CtpSimulationExecutionRegistration
from backtrader_runtime.registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)

from . import managed_case_scope


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INVOCATION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ISSUED_BINDING_REFS: dict[int, weakref.ReferenceType["ManagedCaseInvocationBinding"]] = {}


class ManagedCaseInvocationError(ValueError):
    """Redacted rejection from offline case invocation binding."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> NoReturn:
    raise ManagedCaseInvocationError(reason)


def _require_digest(value: Any, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject(reason)
    return value


def _json_digest(value: Any, reason: str) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except Exception:
        _reject(reason)
    return hashlib.sha256(payload).hexdigest()


def _front_pair_data(pair: CtpConfiguredFrontPair) -> dict[str, str]:
    if type(pair) is not CtpConfiguredFrontPair:
        _reject("invocation_selection_invalid")
    if type(pair.md_front) is not str or type(pair.td_front) is not str:
        _reject("invocation_selection_invalid")
    return {"md_front": pair.md_front, "td_front": pair.td_front}


def _number(value: Any, reason: str) -> Optional[float]:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or type(value) not in (int, float)
        or not math.isfinite(float(value))
        or value < 0
    ):
        _reject(reason)
    return float(value)


def _endpoint_projection(
    endpoint: CtpFrontEndpointEvidence,
    expected_front: str,
    repeated_samples: int,
) -> tuple[dict[str, Any], Optional[float]]:
    if (
        type(endpoint) is not CtpFrontEndpointEvidence
        or type(endpoint.front) is not str
        or endpoint.front != expected_front
        or type(endpoint.samples) is not tuple
        or len(endpoint.samples) != repeated_samples
    ):
        _reject("invocation_selection_invalid")

    sample_rows = []
    successful_latencies = []
    for sample in endpoint.samples:
        if type(sample) is not CtpFrontProbeSample or type(sample.connected) is not bool:
            _reject("invocation_selection_invalid")
        latency = _number(sample.latency_ms, "invocation_selection_invalid")
        dns_latency = _number(sample.dns_resolution_ms, "invocation_selection_invalid")
        tcp_latency = _number(sample.tcp_connect_ms, "invocation_selection_invalid")
        if sample.failure is not None and (
            type(sample.failure) is not str or not sample.failure or len(sample.failure) > 64
        ):
            _reject("invocation_selection_invalid")
        if sample.connected:
            if (
                sample.failure is not None
                or latency is None
                or dns_latency is None
                or tcp_latency is None
                # Match ctp_front_pair_probe's millisecond rounding tolerance.
                or abs(latency - dns_latency - tcp_latency) > 0.00001
            ):
                _reject("invocation_selection_invalid")
            successful_latencies.append(latency)
        elif (
            sample.failure is None
            or latency is not None
            or dns_latency is not None
            or tcp_latency is not None
        ):
            _reject("invocation_selection_invalid")
        sample_rows.append(
            {
                "connected": sample.connected,
                "dns_resolution_ms": dns_latency,
                "failure": sample.failure,
                "latency_ms": latency,
                "tcp_connect_ms": tcp_latency,
            }
        )

    minimum_successes = repeated_samples // 2 + 1
    if len(successful_latencies) < minimum_successes:
        endpoint_median = None
    else:
        endpoint_median = float(median(successful_latencies))
    return {"front": endpoint.front, "samples": sample_rows}, endpoint_median


def _selection_digest(
    selection: CtpSimNowManagedScopeSelection,
    configured_pairs: tuple[tuple[str, str], ...],
) -> str:
    """Validate selection evidence consistency and hash its canonical projection.

    Probe samples remain unauthenticated transport observations. This check
    only mirrors the selector's data-shape and ranking rules.
    """
    try:
        front_selection = selection.front_pair_selection
        if (
            type(front_selection) is not CtpFrontPairSelection
            or type(front_selection.pair) is not CtpConfiguredFrontPair
            or type(front_selection.evidence) is not tuple
            or type(front_selection.config_index) is not int
            or type(front_selection.repeated_samples) is not int
            or not 1 <= front_selection.repeated_samples <= 5
            or type(front_selection.timeout_seconds) not in (int, float)
            or isinstance(front_selection.timeout_seconds, bool)
            or not math.isfinite(float(front_selection.timeout_seconds))
            or not 0 < front_selection.timeout_seconds <= 10
            or type(front_selection.latency_score_ms) not in (int, float)
            or isinstance(front_selection.latency_score_ms, bool)
            or not math.isfinite(float(front_selection.latency_score_ms))
            or front_selection.latency_score_ms < 0
            or len(front_selection.evidence) != len(configured_pairs)
        ):
            _reject("invocation_selection_invalid")

        evidence_rows = []
        eligible = []
        for index, item in enumerate(front_selection.evidence):
            if (
                type(item) is not CtpFrontPairEvidence
                or type(item.config_index) is not int
                or item.config_index != index
                or type(item.reachable) is not bool
                or (item.pair.md_front, item.pair.td_front) != configured_pairs[index]
            ):
                _reject("invocation_selection_invalid")
            md_row, md_median = _endpoint_projection(
                item.md, configured_pairs[index][0], front_selection.repeated_samples
            )
            td_row, td_median = _endpoint_projection(
                item.td, configured_pairs[index][1], front_selection.repeated_samples
            )
            expected_reachable = md_median is not None and td_median is not None
            expected_score = max(md_median, td_median) if expected_reachable else None
            score = _number(item.latency_score_ms, "invocation_selection_invalid")
            if item.reachable is not expected_reachable or score != expected_score:
                _reject("invocation_selection_invalid")
            if expected_reachable:
                eligible.append((expected_score, index))
            evidence_rows.append(
                {
                    "config_index": index,
                    "latency_score_ms": score,
                    "md": md_row,
                    "pair": _front_pair_data(item.pair),
                    "reachable": item.reachable,
                    "td": td_row,
                }
            )

        if not eligible:
            _reject("invocation_selection_invalid")
        best_score, best_index = min(eligible, key=lambda item: (item[0], item[1]))
        if (
            not 0 <= front_selection.config_index < len(configured_pairs)
            or front_selection.config_index != best_index
            or front_selection.pair != front_selection.evidence[best_index].pair
            or float(front_selection.latency_score_ms) != best_score
        ):
            _reject("invocation_selection_invalid")
        if type(selection.execution_registration) is not CtpSimulationExecutionRegistration:
            _reject("invocation_selection_invalid")
        registration_digest = selection.execution_registration.digest
        _require_digest(registration_digest, "invocation_selection_invalid")
        return _json_digest(
            {
                "config_digest": selection.config_digest,
                "effective_digest": selection.effective_digest,
                "evidence": evidence_rows,
                "front_pair_set_sha256": selection.front_pair_set_sha256,
                "profile_digest": selection.profile_digest,
                "registration_digest": registration_digest,
                "selected_config_index": front_selection.config_index,
                "selected_pair": _front_pair_data(front_selection.pair),
            },
            "invocation_selection_invalid",
        )
    except ManagedCaseInvocationError:
        raise
    except Exception:
        _reject("invocation_selection_invalid")


def _validate_lease_snapshot(
    snapshot: Optional[ManagedCtpMdLeaseSnapshot], account_fingerprint: str
) -> Optional[int]:
    """Accept no lease claim until a trusted owner can verify current state."""

    if snapshot is None:
        return None
    if (
        type(snapshot) is not ManagedCtpMdLeaseSnapshot
        or type(snapshot.account_fingerprint_sha256) is not str
        or _SHA256_RE.fullmatch(snapshot.account_fingerprint_sha256) is None
        or snapshot.account_fingerprint_sha256 != account_fingerprint
        or type(snapshot.lease_generation) is not int
        or snapshot.lease_generation <= 0
        or snapshot.active is not True
    ):
        _reject("invocation_lease_snapshot_invalid")
    # This public frozen dataclass is caller-constructible and replayable.
    # Field validation cannot prove owner issuance or lease freshness.
    _reject("invocation_lease_verifier_unavailable")


def _current_sealed_config(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> tuple[EffectiveRuntimeConfig, Any]:
    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("invocation_sealed_runtime_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
    except Exception:
        _reject("invocation_sealed_runtime_invalid")
    if (
        current.registration is not effective.registration
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
    ):
        _reject("invocation_runtime_config_changed")
    try:
        private = _private_config(current)
    except Exception:
        _reject("invocation_private_config_invalid")
    return current, private


def _require_current_case_files(
    case_id: str, scenario_id: str, case_scope: managed_case_scope.CertificationCaseScope
) -> None:
    """Recheck the non-secret child config, strategy plan, and wrapper bytes."""

    entry = managed_case_scope.managed_case_entry
    try:
        case_file = entry._expected_script(case_id)
        if not entry._is_exact_direct_case_path(case_id, case_file):
            _reject("invocation_case_files_invalid")
        runner_digest = hashlib.sha256(case_file.read_bytes()).hexdigest()
        case_config_digest = entry._validated_case_config_digest(case_file, case_id)
        strategy_path = case_file.parent / f"{case_id}_strategy.py"
        if strategy_path.is_symlink() or not strategy_path.is_file():
            _reject("invocation_case_files_invalid")
        strategy_plan = managed_case_scope.load_descriptive_case_plan(
            strategy_path,
            expected_case_id=case_id,
            expected_scenario_id=scenario_id,
        )
    except ManagedCaseInvocationError:
        raise
    except Exception:
        _reject("invocation_case_files_invalid")
    if (
        case_config_digest is None
        or runner_digest != case_scope.runner_digest
        or case_config_digest != case_scope.case_config_digest
        or strategy_plan.source_sha256 != case_scope.strategy_plan_digest
    ):
        _reject("invocation_case_files_changed")


def _validate_inputs(
    case_scope: managed_case_scope.CertificationCaseScope,
    selection: CtpSimNowManagedScopeSelection,
    invocation_id: str,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    lease_snapshot: Optional[ManagedCtpMdLeaseSnapshot],
) -> dict[str, Any]:
    if (
        type(case_scope) is not managed_case_scope.CertificationCaseScope
        or not managed_case_scope._is_issued_scope(case_scope)
    ):
        _reject("invocation_case_scope_invalid")
    if type(selection) is not CtpSimNowManagedScopeSelection:
        _reject("invocation_selection_invalid")
    if (
        type(invocation_id) is not str
        or _INVOCATION_ID_RE.fullmatch(invocation_id) is None
    ):
        _reject("invocation_id_invalid")

    try:
        scenario = managed_case_scope.managed_case_entry._load_code_owned_scenarios().get(
            case_scope.case_id
        )
    except Exception:
        _reject("invocation_case_scope_invalid")
    if (
        scenario is None
        or case_scope.scenario_id != scenario.scenario_id
        or case_scope.account_identity_scheme != managed_case_scope.ACCOUNT_IDENTITY_SCHEME
    ):
        _reject("invocation_case_scope_invalid")
    _require_current_case_files(case_scope.case_id, scenario.scenario_id, case_scope)
    for value in (
        case_scope.account_identity_sha256,
        case_scope.suite_config_digest,
        case_scope.suite_effective_digest,
        case_scope.case_config_digest,
        case_scope.strategy_plan_digest,
        case_scope.runner_digest,
    ):
        _require_digest(value, "invocation_case_scope_invalid")

    current, private = _current_sealed_config(effective, registry)
    if (
        type(selection.execution_registration) is not CtpSimulationExecutionRegistration
        or type(selection.front_pair_selection) is not CtpFrontPairSelection
    ):
        _reject("invocation_selection_invalid")
    registration = selection.execution_registration
    front_selection = selection.front_pair_selection
    if (
        case_scope.runtime_id != current.registration.runtime_id
        or case_scope.suite_config_digest != current.config.config_digest
        or case_scope.suite_effective_digest != current.effective_digest
        or selection.config_digest != current.config.config_digest
        or selection.effective_digest != current.effective_digest
        or registration.runtime_registration is not current.registration
        or registration.config_digest != current.config.config_digest
        or registration.effective_digest != current.effective_digest
        or registration.profile_digest
        != (None if current.profile is None else current.profile.digest)
        or selection.profile_digest != registration.profile_digest
    ):
        _reject("invocation_config_scope_mismatch")

    try:
        case_account_digest = managed_case_scope._account_identity_sha256(current)
        account_fingerprint = hashlib.sha256(
            f"{private.broker_id}:{private.user_id}".encode("utf-8")
        ).hexdigest()[:16]
        execution_account_digest = hashlib.sha256(
            ("acct_" + account_fingerprint).encode("ascii")
        ).hexdigest()
        configured_pairs = tuple(
            (pair["md_front"], pair["td_front"]) for pair in private.front_pairs
        )
        pair_set_digest = ctp_simnow_front_pair_set_sha256(private.front_pairs)
    except Exception:
        _reject("invocation_private_config_invalid")
    selection_digest = _selection_digest(selection, configured_pairs)
    selected_pair = (front_selection.pair.md_front, front_selection.pair.td_front)
    if (
        case_scope.account_identity_scheme != managed_case_scope.ACCOUNT_IDENTITY_SCHEME
        or case_scope.account_identity_sha256 != case_account_digest
        or registration.account_fingerprint_sha256 != execution_account_digest
    ):
        _reject("invocation_account_scope_mismatch")
    if (
        registration.instrument_id != private.instrument_id
        or registration.exchange_id != private.exchange_id
        or registration.hedge_flag != private.hedge_flag
    ):
        _reject("invocation_contract_scope_mismatch")
    if (
        selection.front_pair_set_sha256 != pair_set_digest
        or registration.front_pair_set_sha256 != pair_set_digest
        or type(front_selection.config_index) is not int
        or not 0 <= front_selection.config_index < len(configured_pairs)
        or configured_pairs[front_selection.config_index] != selected_pair
        or selected_pair != (registration.md_front, registration.td_front)
    ):
        _reject("invocation_pair_scope_mismatch")

    lease_generation = _validate_lease_snapshot(
        lease_snapshot, registration.account_fingerprint_sha256
    )
    registration_digest = _require_digest(
        registration.digest, "invocation_registration_invalid"
    )
    return {
        "account_identity_scheme": case_scope.account_identity_scheme,
        "account_identity_sha256": case_account_digest,
        "account_fingerprint_sha256": registration.account_fingerprint_sha256,
        "case_id": case_scope.case_id,
        "case_scope": case_scope,
        "case_scope_sha256": _json_digest(
            {
                "account_identity_scheme": case_scope.account_identity_scheme,
                "account_identity_sha256": case_scope.account_identity_sha256,
                "case_config_digest": case_scope.case_config_digest,
                "case_id": case_scope.case_id,
                "runner_digest": case_scope.runner_digest,
                "runtime_id": case_scope.runtime_id,
                "scenario_id": case_scope.scenario_id,
                "strategy_plan_digest": case_scope.strategy_plan_digest,
                "suite_config_digest": case_scope.suite_config_digest,
                "suite_effective_digest": case_scope.suite_effective_digest,
            },
            "invocation_case_scope_invalid",
        ),
        "config_digest": current.config.config_digest,
        "effective_digest": current.effective_digest,
        "exchange_id": registration.exchange_id,
        "instrument_id": registration.instrument_id,
        "invocation_id": invocation_id,
        "lease_generation": lease_generation,
        "md_front": registration.md_front,
        "pair_sha256": _json_digest(
            [registration.md_front, registration.td_front],
            "invocation_pair_scope_mismatch",
        ),
        "pair_set_sha256": pair_set_digest,
        "registration_digest": registration_digest,
        "runner_digest": case_scope.runner_digest,
        "scenario_id": case_scope.scenario_id,
        "selection": selection,
        "selection_digest": selection_digest,
        "strategy_plan_digest": case_scope.strategy_plan_digest,
        "td_front": registration.td_front,
        "lease_snapshot": lease_snapshot,
    }


@dataclass(frozen=True)
class ManagedCaseInvocationBinding:
    """Immutable, non-authorizing identities for one 007 case invocation."""

    invocation_id: str
    case_id: str
    scenario_id: str
    account_identity_scheme: str
    account_identity_sha256: str
    config_digest: str
    effective_digest: str
    pair_set_sha256: str
    pair_sha256: str
    registration_digest: str
    selection_digest: str
    instrument_id: str
    exchange_id: str
    strategy_plan_digest: str
    runner_digest: str
    # Always None until a trusted live lease-owner verifier is integrated.
    lease_generation: Optional[int]
    context_sha256: str
    md_front: str = field(repr=False)
    td_front: str = field(repr=False)
    _case_scope: managed_case_scope.CertificationCaseScope = field(repr=False, compare=False)
    _selection: CtpSimNowManagedScopeSelection = field(repr=False, compare=False)
    _lease_snapshot: Optional[ManagedCtpMdLeaseSnapshot] = field(repr=False, compare=False)

    def as_redacted_dict(self) -> dict[str, Any]:
        """Return a log-safe summary with no endpoint or credential values."""

        return {
            "account_identity_scheme": self.account_identity_scheme,
            "account_identity_sha256": self.account_identity_sha256,
            "case_id": self.case_id,
            "config_digest": self.config_digest,
            "context_sha256": self.context_sha256,
            "effective_digest": self.effective_digest,
            "exchange_id": self.exchange_id,
            "instrument_id": self.instrument_id,
            "invocation_id": self.invocation_id,
            "lease_generation": self.lease_generation,
            "pair_sha256": self.pair_sha256,
            "pair_set_sha256": self.pair_set_sha256,
            "registration_digest": self.registration_digest,
            "runner_digest": self.runner_digest,
            "scenario_id": self.scenario_id,
            "selection_digest": self.selection_digest,
            "strategy_plan_digest": self.strategy_plan_digest,
        }


def _remember_binding(binding: ManagedCaseInvocationBinding) -> None:
    identity = id(binding)

    def discard(reference: weakref.ReferenceType[ManagedCaseInvocationBinding]) -> None:
        if _ISSUED_BINDING_REFS.get(identity) is reference:
            _ISSUED_BINDING_REFS.pop(identity, None)

    _ISSUED_BINDING_REFS[identity] = weakref.ref(binding, discard)


def bind_case_invocation(
    case_scope: managed_case_scope.CertificationCaseScope,
    selection: CtpSimNowManagedScopeSelection,
    invocation_id: str,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    lease_snapshot: Optional[ManagedCtpMdLeaseSnapshot] = None,
) -> ManagedCaseInvocationBinding:
    """Bind offline provenance; ``lease_snapshot`` must be None without a trusted owner verifier."""

    values = _validate_inputs(
        case_scope, selection, invocation_id, effective, registry, lease_snapshot
    )
    payload = {
        key: value
        for key, value in values.items()
        if key
        not in {
            "case_scope",
            "lease_snapshot",
            "md_front",
            "selection",
            "td_front",
        }
    }
    context_sha256 = _json_digest(payload, "invocation_binding_invalid")
    binding = ManagedCaseInvocationBinding(
        invocation_id=invocation_id,
        case_id=values["case_id"],
        scenario_id=values["scenario_id"],
        account_identity_scheme=values["account_identity_scheme"],
        account_identity_sha256=values["account_identity_sha256"],
        config_digest=values["config_digest"],
        effective_digest=values["effective_digest"],
        pair_set_sha256=values["pair_set_sha256"],
        pair_sha256=values["pair_sha256"],
        registration_digest=values["registration_digest"],
        selection_digest=values["selection_digest"],
        instrument_id=values["instrument_id"],
        exchange_id=values["exchange_id"],
        strategy_plan_digest=values["strategy_plan_digest"],
        runner_digest=values["runner_digest"],
        lease_generation=values["lease_generation"],
        context_sha256=context_sha256,
        md_front=values["md_front"],
        td_front=values["td_front"],
        _case_scope=case_scope,
        _selection=selection,
        _lease_snapshot=lease_snapshot,
    )
    _remember_binding(binding)
    return binding


def validate_case_invocation(
    binding: ManagedCaseInvocationBinding,
    case_scope: managed_case_scope.CertificationCaseScope,
    selection: CtpSimNowManagedScopeSelection,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    lease_snapshot: Optional[ManagedCtpMdLeaseSnapshot] = None,
) -> None:
    """Reject drift; caller lease claims remain unsupported without an owner verifier."""

    reference = _ISSUED_BINDING_REFS.get(id(binding))
    if (
        type(binding) is not ManagedCaseInvocationBinding
        or reference is None
        or reference() is not binding
        or binding._case_scope is not case_scope
        or binding._selection is not selection
    ):
        _reject("invocation_binding_invalid")
    values = _validate_inputs(
        case_scope,
        selection,
        binding.invocation_id,
        effective,
        registry,
        lease_snapshot,
    )
    payload = {
        key: value
        for key, value in values.items()
        if key
        not in {
            "case_scope",
            "lease_snapshot",
            "md_front",
            "selection",
            "td_front",
        }
    }
    if (
        _json_digest(payload, "invocation_binding_invalid") != binding.context_sha256
        or values["lease_generation"] != binding.lease_generation
        or values["selection_digest"] != binding.selection_digest
        or values["registration_digest"] != binding.registration_digest
        or values["pair_set_sha256"] != binding.pair_set_sha256
        or values["pair_sha256"] != binding.pair_sha256
        or values["account_identity_sha256"] != binding.account_identity_sha256
        or values["config_digest"] != binding.config_digest
        or values["effective_digest"] != binding.effective_digest
        or values["instrument_id"] != binding.instrument_id
        or values["exchange_id"] != binding.exchange_id
        or values["strategy_plan_digest"] != binding.strategy_plan_digest
        or values["runner_digest"] != binding.runner_digest
        or values["md_front"] != binding.md_front
        or values["td_front"] != binding.td_front
    ):
        _reject("invocation_identity_drift")


__all__ = [
    "ManagedCaseInvocationBinding",
    "ManagedCaseInvocationError",
    "bind_case_invocation",
    "validate_case_invocation",
]
