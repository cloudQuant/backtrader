"""Bounded, credential-free TCP diagnostics for sealed configured CTP fronts.

This is an operator diagnostic only. It consumes the exact sealed 013_3
simulation/sandbox configuration, opens TCP sockets only to the configured
MD/TD candidates, and projects the result to pair indexes and sample counts.
Schema validation parses the same protected config bytes, which include CTP
authentication fields, but this module never accesses those field values,
invokes the credential resolver, imports an SDK, performs a login, or starts a
trading route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairProbeError,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
    select_ctp_front_pair,
)
from .ctp_sandbox_readonly_admission import require_ctp_sandbox_profile_runtime
from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
)
from .registry import EffectiveRuntimeConfig, RuntimeRegistry


_PROBE_TIMEOUT_SECONDS = 3.0
_PROBE_MAX_PAIRS = 8
_PROBE_REPEATED_SAMPLES = 3
_PAIR_STATUS_VALUES = frozenset({"reachable", "partial", "unreachable", "unavailable"})
_RESULT_STATUS_VALUES = frozenset({"selected", "no_pair_reachable", "rejected"})
_RESULT_REASON_VALUES = frozenset(
    {
        "selected_configured_pair",
        "no_configured_pair_reachable",
        "front_probe_rejected",
        "runtime_profile_rejected",
    }
)


@dataclass(frozen=True)
class CtpConfiguredFrontPairCheck:
    config_index: int
    md_connected_count: int
    md_sample_count: int
    td_connected_count: int
    td_sample_count: int
    status: str

    def __post_init__(self) -> None:
        if (
            type(self.config_index) is not int
            or not 0 <= self.config_index < _PROBE_MAX_PAIRS
            or type(self.md_connected_count) is not int
            or type(self.md_sample_count) is not int
            or type(self.td_connected_count) is not int
            or type(self.td_sample_count) is not int
            or not 0 <= self.md_connected_count <= self.md_sample_count <= _PROBE_REPEATED_SAMPLES
            or not 0 <= self.td_connected_count <= self.td_sample_count <= _PROBE_REPEATED_SAMPLES
            or self.status not in _PAIR_STATUS_VALUES
        ):
            raise ValueError("front_check_pair_result_invalid")

    def as_public_dict(self) -> dict[str, object]:
        return {
            "config_index": self.config_index,
            "md_connected_count": self.md_connected_count,
            "md_sample_count": self.md_sample_count,
            "status": self.status,
            "td_connected_count": self.td_connected_count,
            "td_sample_count": self.td_sample_count,
        }


@dataclass(frozen=True)
class CtpConfiguredFrontCheckResult:
    status: str
    reason: str
    configured_pair_count: int
    selected_config_index: Optional[int]
    pairs: tuple[CtpConfiguredFrontPairCheck, ...]

    def __post_init__(self) -> None:
        if (
            self.status not in _RESULT_STATUS_VALUES
            or self.reason not in _RESULT_REASON_VALUES
            or type(self.configured_pair_count) is not int
            or not 1 <= self.configured_pair_count <= _PROBE_MAX_PAIRS
            or type(self.pairs) is not tuple
            or len(self.pairs) != self.configured_pair_count
            or tuple(item.config_index for item in self.pairs)
            != tuple(range(self.configured_pair_count))
            or (
                self.selected_config_index is not None
                and (
                    type(self.selected_config_index) is not int
                    or not 0 <= self.selected_config_index < self.configured_pair_count
                )
            )
            or (self.status == "selected") != (self.selected_config_index is not None)
        ):
            raise ValueError("front_check_result_invalid")

    @property
    def succeeded(self) -> bool:
        return self.status == "selected"

    def as_public_dict(self) -> dict[str, object]:
        return {
            "authentication_attempted": False,
            "configured_pair_count": self.configured_pair_count,
            "credential_resolver_invoked": False,
            "order_submission_authorized": False,
            "pairs": [item.as_public_dict() for item in self.pairs],
            "provider_login_started": False,
            "reason": self.reason,
            "sdk_imported": False,
            "selected_config_index": self.selected_config_index,
            "settlement_writes": 0,
            "status": self.status,
            "tcp_probe_only": True,
            "trading_writes": 0,
        }


def _front_pair(front_pair: object) -> tuple[str, str]:
    if not isinstance(front_pair, Mapping):
        _reject("front_config_rejected")
    td_front = front_pair.get("td_front")
    md_front = front_pair.get("md_front")
    if type(td_front) is not str or type(md_front) is not str:
        _reject("front_config_rejected")
    return td_front, md_front


def _endpoint_counts(value: object) -> tuple[int, int]:
    if type(value) is not CtpFrontEndpointEvidence or type(value.samples) is not tuple:
        _reject("front_probe_rejected")
    samples = value.samples
    if len(samples) != _PROBE_REPEATED_SAMPLES:
        _reject("front_probe_rejected")
    for sample in samples:
        if type(sample) is not CtpFrontProbeSample or type(sample.connected) is not bool:
            _reject("front_probe_rejected")
        if sample.connected and (
            type(sample.latency_ms) not in (int, float)
            or not math.isfinite(sample.latency_ms)
            or sample.latency_ms < 0
        ):
            _reject("front_probe_rejected")
    return sum(sample.connected is True for sample in samples), len(samples)


def _pair_status(md_connected: int, md_count: int, td_connected: int, td_count: int) -> str:
    if (
        md_count > 0
        and td_count > 0
        and md_connected >= md_count // 2 + 1
        and td_connected >= td_count // 2 + 1
    ):
        return "reachable"
    if md_connected or td_connected:
        return "partial"
    return "unreachable"


def _project_evidence(
    evidence: object, *, front_pairs: tuple[Any, ...]
) -> tuple[CtpConfiguredFrontPairCheck, ...]:
    configured_pair_count = len(front_pairs)
    if type(evidence) is not tuple or len(evidence) > configured_pair_count:
        _reject("front_probe_rejected")
    by_index: dict[int, CtpFrontPairEvidence] = {}
    for item in evidence:
        if (
            type(item) is not CtpFrontPairEvidence
            or type(item.config_index) is not int
            or not 0 <= item.config_index < configured_pair_count
            or item.config_index in by_index
            or type(item.pair) is not CtpConfiguredFrontPair
        ):
            _reject("front_probe_rejected")
        td_front, md_front = _front_pair(front_pairs[item.config_index])
        if (
            (item.pair.td_front, item.pair.md_front) != (td_front, md_front)
            or type(item.md) is not CtpFrontEndpointEvidence
            or type(item.td) is not CtpFrontEndpointEvidence
            or item.md.front != md_front
            or item.td.front != td_front
        ):
            _reject("front_probe_rejected")
        by_index[item.config_index] = item

    projected = []
    for index in range(configured_pair_count):
        item = by_index.get(index)
        if item is None:
            projected.append(CtpConfiguredFrontPairCheck(index, 0, 0, 0, 0, "unavailable"))
            continue
        md_connected, md_count = _endpoint_counts(item.md)
        td_connected, td_count = _endpoint_counts(item.td)
        status = _pair_status(md_connected, md_count, td_connected, td_count)
        if type(item.reachable) is not bool or item.reachable is not (status == "reachable"):
            _reject("front_probe_rejected")
        md_median = item.md.median_latency_ms
        td_median = item.td.median_latency_ms
        expected_score = (
            max(md_median, td_median)
            if status == "reachable" and md_median is not None and td_median is not None
            else None
        )
        if item.latency_score_ms != expected_score:
            _reject("front_probe_rejected")
        projected.append(
            CtpConfiguredFrontPairCheck(
                index,
                md_connected,
                md_count,
                td_connected,
                td_count,
                status,
            )
        )
    return tuple(projected)


def _validate_selection(
    selection: object,
    *,
    front_pairs: tuple[Any, ...],
    projected: tuple[CtpConfiguredFrontPairCheck, ...],
) -> int:
    if (
        type(selection) is not CtpFrontPairSelection
        or type(selection.config_index) is not int
        or not 0 <= selection.config_index < len(front_pairs)
        or type(selection.pair) is not CtpConfiguredFrontPair
        or projected[selection.config_index].status != "reachable"
        or selection.repeated_samples != _PROBE_REPEATED_SAMPLES
        or type(selection.evidence) is not tuple
        or len(selection.evidence) != len(front_pairs)
        or any(
            type(item) is not CtpFrontPairEvidence or item.config_index != index
            for index, item in enumerate(selection.evidence)
        )
    ):
        _reject("front_probe_rejected")
    td_front, md_front = _front_pair(front_pairs[selection.config_index])
    if (selection.pair.td_front, selection.pair.md_front) != (td_front, md_front):
        _reject("front_probe_rejected")
    eligible = tuple(item for item in selection.evidence if item.reachable)
    if (
        not eligible
        or selection.latency_score_ms != selection.evidence[selection.config_index].latency_score_ms
        or min(eligible, key=lambda item: (item.latency_score_ms, item.config_index)).config_index
        != selection.config_index
    ):
        _reject("front_probe_rejected")
    return selection.config_index


def check_configured_ctp_fronts(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> CtpConfiguredFrontCheckResult:
    """Probe only the exact sealed 013_3 simulation/sandbox front candidates."""

    try:
        profile = require_ctp_sandbox_profile_runtime(effective, registry)
    except Exception:
        _reject("runtime_profile_rejected")
    if effective.mode != "simulation" or effective.preset != "sandbox":
        _reject("runtime_profile_rejected")
    try:
        registration = registry.require_runtime_dir(effective.config.strategy_dir)
        if (
            registration is not effective.registration
            or registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
            or registration.runtime_dir != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
            or effective.profile is not profile
        ):
            _reject("runtime_profile_rejected")
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        if (
            type(binding) is not CtpSimNowConfigReadOnlyBinding
            or binding.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
        ):
            _reject("runtime_profile_rejected")
        private, bound_registration, front_pairs = binding._sealed_private_config(
            effective, registry
        )
    except RuntimeConfigError:
        raise
    except Exception:
        _reject("runtime_profile_rejected")
    if (
        bound_registration is not registration
        or type(front_pairs) is not tuple
        or not 1 <= len(front_pairs) <= _PROBE_MAX_PAIRS
        or any(_front_pair(pair) is None for pair in front_pairs)
        or type(getattr(private, "instrument_id", None)) is not str
        or type(getattr(private, "exchange_id", None)) is not str
        or type(getattr(private, "hedge_flag", None)) is not str
    ):
        _reject("front_config_rejected")

    try:
        selection = select_ctp_front_pair(
            front_pairs,
            timeout_seconds=_PROBE_TIMEOUT_SECONDS,
            max_pairs=_PROBE_MAX_PAIRS,
            repeated_samples=_PROBE_REPEATED_SAMPLES,
        )
    except CtpFrontPairProbeError as error:
        try:
            pairs = _project_evidence(error.evidence, front_pairs=front_pairs)
        except RuntimeConfigError:
            return CtpConfiguredFrontCheckResult(
                "rejected",
                "front_probe_rejected",
                len(front_pairs),
                None,
                tuple(
                    CtpConfiguredFrontPairCheck(index, 0, 0, 0, 0, "unavailable")
                    for index in range(len(front_pairs))
                ),
            )
        if error.reason == "no_configured_front_pair_reachable":
            return CtpConfiguredFrontCheckResult(
                "no_pair_reachable",
                "no_configured_pair_reachable",
                len(front_pairs),
                None,
                pairs,
            )
        return CtpConfiguredFrontCheckResult(
            "rejected", "front_probe_rejected", len(front_pairs), None, pairs
        )
    except Exception:
        return CtpConfiguredFrontCheckResult(
            "rejected",
            "front_probe_rejected",
            len(front_pairs),
            None,
            tuple(
                CtpConfiguredFrontPairCheck(index, 0, 0, 0, 0, "unavailable")
                for index in range(len(front_pairs))
            ),
        )

    try:
        pairs = _project_evidence(selection.evidence, front_pairs=front_pairs)
        selected_index = _validate_selection(
            selection,
            front_pairs=front_pairs,
            projected=pairs,
        )
    except RuntimeConfigError:
        _reject("front_probe_rejected")
    return CtpConfiguredFrontCheckResult(
        "selected", "selected_configured_pair", len(front_pairs), selected_index, pairs
    )


def _reject(reason: str) -> None:
    reasons = {
        "front_config_rejected",
        "front_probe_rejected",
        "runtime_profile_rejected",
    }
    safe_reason = reason if reason in reasons else "runtime_profile_rejected"
    raise RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "configured CTP front check was rejected by the sealed zero-write policy",
        field_path="runtime.preset",
        reason=safe_reason,
    )


__all__ = [
    "CtpConfiguredFrontCheckResult",
    "CtpConfiguredFrontPairCheck",
    "check_configured_ctp_fronts",
]
