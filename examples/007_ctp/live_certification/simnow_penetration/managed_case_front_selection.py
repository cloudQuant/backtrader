"""Offline, non-authorizing 007 front-selection receipts.

A receipt binds one bounded local TCP front-check result to an issued case
scope and the freshly revalidated sealed 007 config. It carries only digests,
indexes, counts, and local origins; no endpoint or credential values. It does
not authenticate a provider, authorize execution, or certify a case.
"""

from __future__ import annotations

import hashlib
import json
import re
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NoReturn

from backtrader_runtime import ctp_configured_front_check
from backtrader_runtime.ctp_simnow_managed_operator import (
    ctp_simnow_front_pair_set_sha256,
)
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.inventory import ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
from backtrader_runtime.registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)

from . import managed_case_scope

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ORIGIN = "local_007_configured_tcp_front_check"
_CLOCK_ORIGIN = "local_system_utc_clock"
_ISSUED_RECEIPT_REFS: dict[
    int, weakref.ReferenceType[ManagedCaseFrontSelectionReceipt]
] = {}


class ManagedCaseFrontSelectionError(ValueError):
    """Redacted rejection for the offline 007 front-selection receipt."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> NoReturn:
    raise ManagedCaseFrontSelectionError(reason)


def _digest(value: Any, reason: str) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError):
        _reject(reason)
    return hashlib.sha256(raw).hexdigest()


def _current_007_config(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> tuple[EffectiveRuntimeConfig, str, int]:
    if (
        type(effective) is not EffectiveRuntimeConfig
        or type(registry) is not RuntimeRegistry
    ):
        _reject("front_selection_sealed_runtime_required")
    try:
        require_effective_runtime_config_seal(effective, registry)
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
        if (
            current.registration is not effective.registration
            or current.registration.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
            or current.config.config_digest != effective.config.config_digest
            or current.effective_digest != effective.effective_digest
        ):
            _reject("front_selection_runtime_config_changed")
        binding = registry.require_ctp_simnow_readonly_binding(
            current.registration.runtime_id
        )
        if (
            type(binding) is not CtpSimNowConfigReadOnlyBinding
            or binding.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
        ):
            _reject("front_selection_config_binding_invalid")
        private, registration, front_pairs = binding._sealed_private_config(
            current, registry
        )
        if (
            registration is not current.registration
            or type(front_pairs) is not tuple
            or not 1 <= len(front_pairs) <= 8
            or any(
                not isinstance(pair, Mapping)
                or set(pair) != {"md_front", "td_front"}
                or type(pair.get("md_front")) is not str
                or type(pair.get("td_front")) is not str
                for pair in front_pairs
            )
            or type(getattr(private, "instrument_id", None)) is not str
        ):
            _reject("front_selection_config_invalid")
        pair_set_sha256 = ctp_simnow_front_pair_set_sha256(front_pairs)
    except ManagedCaseFrontSelectionError:
        raise
    except (
        RuntimeConfigError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        OSError,
    ):
        _reject("front_selection_sealed_runtime_invalid")
    return current, pair_set_sha256, len(front_pairs)


def _probe_payload(result: Any) -> dict[str, Any]:
    """Project only the checker’s endpoint-free counts/status for hashing."""

    if (
        type(result) is not ctp_configured_front_check.CtpConfiguredFrontCheckResult
        or result.status != "selected"
        or result.reason != "selected_configured_pair"
        or type(result.configured_pair_count) is not int
        or type(result.selected_config_index) is not int
        or type(result.pairs) is not tuple
        or len(result.pairs) != result.configured_pair_count
        or not 1 <= result.configured_pair_count <= 8
        or not 0 <= result.selected_config_index < result.configured_pair_count
    ):
        _reject("front_selection_probe_not_selected")
    rows = []
    for expected_index, pair in enumerate(result.pairs):
        if (
            type(pair) is not ctp_configured_front_check.CtpConfiguredFrontPairCheck
            or pair.config_index != expected_index
        ):
            _reject("front_selection_probe_result_invalid")
        rows.append(
            {
                "config_index": pair.config_index,
                "md_connected_count": pair.md_connected_count,
                "md_sample_count": pair.md_sample_count,
                "status": pair.status,
                "td_connected_count": pair.td_connected_count,
                "td_sample_count": pair.td_sample_count,
            }
        )
    if result.pairs[result.selected_config_index].status != "reachable":
        _reject("front_selection_probe_result_invalid")
    return {
        "configured_pair_count": result.configured_pair_count,
        "pairs": rows,
        "reason": result.reason,
        "selected_config_index": result.selected_config_index,
        "status": result.status,
    }


def _case_scope_sha256(case_scope: managed_case_scope.CertificationCaseScope) -> str:
    return _digest(
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
        "front_selection_case_scope_digest_failed",
    )


def _receipt_payload(receipt: ManagedCaseFrontSelectionReceipt) -> dict[str, Any]:
    return {
        "case_id": receipt.case_id,
        "case_scope_sha256": receipt.case_scope_sha256,
        "checked_at_utc": receipt.checked_at_utc,
        "clock_origin": receipt.clock_origin,
        "config_digest": receipt.config_digest,
        "effective_digest": receipt.effective_digest,
        "ordered_front_pair_set_sha256": receipt.ordered_front_pair_set_sha256,
        "probe_origin": receipt.probe_origin,
        "probe_result_sha256": receipt.probe_result_sha256,
        "receipt_version": receipt.receipt_version,
        "runtime_id": receipt.runtime_id,
        "scenario_id": receipt.scenario_id,
        "selected_config_index": receipt.selected_config_index,
        "configured_pair_count": receipt.configured_pair_count,
    }


@dataclass(frozen=True)
class ManagedCaseFrontSelectionReceipt:
    """Immutable local front-check receipt bound to one issued 007 case scope."""

    receipt_version: int
    case_id: str
    case_scope_sha256: str
    scenario_id: str
    runtime_id: str
    config_digest: str
    effective_digest: str
    ordered_front_pair_set_sha256: str
    selected_config_index: int
    configured_pair_count: int
    probe_result_sha256: str
    probe_origin: str
    checked_at_utc: str
    clock_origin: str
    receipt_sha256: str
    _case_scope: managed_case_scope.CertificationCaseScope = field(
        repr=False, compare=False
    )
    _probe_result: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.receipt_version) is not int
            or self.receipt_version != 1
            or type(self.case_id) is not str
            or type(self.scenario_id) is not str
            or self.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
            or any(
                _SHA256_RE.fullmatch(value) is None
                for value in (
                    self.case_scope_sha256,
                    self.config_digest,
                    self.effective_digest,
                    self.ordered_front_pair_set_sha256,
                    self.probe_result_sha256,
                    self.receipt_sha256,
                )
            )
            or type(self.selected_config_index) is not int
            or type(self.configured_pair_count) is not int
            or not 1 <= self.configured_pair_count <= 8
            or not 0 <= self.selected_config_index < self.configured_pair_count
            or self.probe_origin != _RECEIPT_ORIGIN
            or type(self.checked_at_utc) is not str
            or not self.checked_at_utc.endswith("+00:00")
            or self.clock_origin != _CLOCK_ORIGIN
            or type(self._case_scope) is not managed_case_scope.CertificationCaseScope
        ):
            raise ValueError("front_selection_receipt_invalid")

    def as_redacted_dict(self) -> dict[str, Any]:
        """Expose local provenance without endpoints, account IDs, or secrets."""

        return {
            "authorization_granted": False,
            "case_id": self.case_id,
            "case_scope_sha256": self.case_scope_sha256,
            "checked_at_utc": self.checked_at_utc,
            "clock_origin": self.clock_origin,
            "config_digest": self.config_digest,
            "configured_pair_count": self.configured_pair_count,
            "effective_digest": self.effective_digest,
            "ordered_front_pair_set_sha256": self.ordered_front_pair_set_sha256,
            "probe_origin": self.probe_origin,
            "probe_result_sha256": self.probe_result_sha256,
            "provider_authenticated": False,
            "receipt_sha256": self.receipt_sha256,
            "runtime_id": self.runtime_id,
            "scenario_id": self.scenario_id,
            "selected_config_index": self.selected_config_index,
        }


def _remember_receipt(receipt: ManagedCaseFrontSelectionReceipt) -> None:
    identity = id(receipt)

    def discard(
        reference: weakref.ReferenceType[ManagedCaseFrontSelectionReceipt],
    ) -> None:
        if _ISSUED_RECEIPT_REFS.get(identity) is reference:
            _ISSUED_RECEIPT_REFS.pop(identity, None)

    _ISSUED_RECEIPT_REFS[identity] = weakref.ref(receipt, discard)


def check_case_front_selection(
    case_scope: managed_case_scope.CertificationCaseScope,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> ManagedCaseFrontSelectionReceipt:
    """Run the configured TCP check and issue a local, non-authorizing receipt."""

    if (
        type(case_scope) is not managed_case_scope.CertificationCaseScope
        or not managed_case_scope._is_issued_scope(case_scope)
        or case_scope.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    ):
        _reject("front_selection_case_scope_invalid")
    current, pair_set_sha256, pair_count = _current_007_config(effective, registry)
    if (
        case_scope.suite_config_digest != current.config.config_digest
        or case_scope.suite_effective_digest != current.effective_digest
    ):
        _reject("front_selection_case_config_mismatch")

    try:
        result = ctp_configured_front_check.check_configured_ctp_fronts(
            current, registry
        )
    except (RuntimeConfigError, OSError, TypeError, ValueError):
        _reject("front_selection_probe_rejected")
    payload = _probe_payload(result)
    if result.configured_pair_count != pair_count:
        _reject("front_selection_pair_count_mismatch")

    # Re-read the sealed config after probing to catch config drift during the
    # local socket sample window before binding the result to this identity.
    after, after_pair_set_sha256, after_pair_count = _current_007_config(
        effective, registry
    )
    if (
        after.registration is not current.registration
        or after.config.config_digest != current.config.config_digest
        or after.effective_digest != current.effective_digest
        or after_pair_set_sha256 != pair_set_sha256
        or after_pair_count != pair_count
    ):
        _reject("front_selection_runtime_config_changed_during_probe")

    now = datetime.now(timezone.utc).isoformat()
    probe_digest = _digest(payload, "front_selection_probe_digest_failed")
    provisional = {
        "case_id": case_scope.case_id,
        "case_scope_sha256": _case_scope_sha256(case_scope),
        "checked_at_utc": now,
        "clock_origin": _CLOCK_ORIGIN,
        "config_digest": current.config.config_digest,
        "effective_digest": current.effective_digest,
        "ordered_front_pair_set_sha256": pair_set_sha256,
        "probe_origin": _RECEIPT_ORIGIN,
        "probe_result_sha256": probe_digest,
        "receipt_version": 1,
        "runtime_id": current.registration.runtime_id,
        "scenario_id": case_scope.scenario_id,
        "selected_config_index": result.selected_config_index,
        "configured_pair_count": pair_count,
    }
    receipt_digest = _digest(provisional, "front_selection_receipt_digest_failed")
    receipt = ManagedCaseFrontSelectionReceipt(
        receipt_version=1,
        case_id=case_scope.case_id,
        case_scope_sha256=_case_scope_sha256(case_scope),
        scenario_id=case_scope.scenario_id,
        runtime_id=current.registration.runtime_id,
        config_digest=current.config.config_digest,
        effective_digest=current.effective_digest,
        ordered_front_pair_set_sha256=pair_set_sha256,
        selected_config_index=result.selected_config_index,
        configured_pair_count=pair_count,
        probe_result_sha256=probe_digest,
        probe_origin=_RECEIPT_ORIGIN,
        checked_at_utc=now,
        clock_origin=_CLOCK_ORIGIN,
        receipt_sha256=receipt_digest,
        _case_scope=case_scope,
        _probe_result=result,
    )
    _remember_receipt(receipt)
    return receipt


def validate_case_front_selection_receipt(
    receipt: ManagedCaseFrontSelectionReceipt,
    case_scope: managed_case_scope.CertificationCaseScope,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> None:
    """Revalidate an issued receipt against its case scope and current config."""

    reference = _ISSUED_RECEIPT_REFS.get(id(receipt))
    if (
        type(receipt) is not ManagedCaseFrontSelectionReceipt
        or reference is None
        or reference() is not receipt
        or type(case_scope) is not managed_case_scope.CertificationCaseScope
        or not managed_case_scope._is_issued_scope(case_scope)
        or receipt._case_scope is not case_scope
        or receipt.case_id != case_scope.case_id
        or receipt.case_scope_sha256 != _case_scope_sha256(case_scope)
        or receipt.scenario_id != case_scope.scenario_id
    ):
        _reject("front_selection_receipt_invalid")
    current, pair_set_sha256, pair_count = _current_007_config(effective, registry)
    if (
        receipt.runtime_id != current.registration.runtime_id
        or receipt.config_digest != current.config.config_digest
        or receipt.effective_digest != current.effective_digest
        or receipt.config_digest != case_scope.suite_config_digest
        or receipt.effective_digest != case_scope.suite_effective_digest
        or receipt.ordered_front_pair_set_sha256 != pair_set_sha256
        or receipt.configured_pair_count != pair_count
        or receipt.selected_config_index >= pair_count
    ):
        _reject("front_selection_receipt_config_mismatch")
    try:
        payload = _probe_payload(receipt._probe_result)
        probe_digest = _digest(payload, "front_selection_probe_digest_failed")
        expected_receipt_digest = _digest(
            _receipt_payload(receipt), "front_selection_receipt_digest_failed"
        )
    except ManagedCaseFrontSelectionError:
        raise
    except (AttributeError, TypeError, ValueError, KeyError):
        _reject("front_selection_receipt_invalid")
    if (
        receipt._probe_result.selected_config_index != receipt.selected_config_index
        or receipt._probe_result.configured_pair_count != receipt.configured_pair_count
        or probe_digest != receipt.probe_result_sha256
        or expected_receipt_digest != receipt.receipt_sha256
    ):
        _reject("front_selection_receipt_digest_mismatch")


def validate_receipt_matches_selection(
    receipt: ManagedCaseFrontSelectionReceipt,
    case_scope: managed_case_scope.CertificationCaseScope,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    *,
    config_digest: str,
    effective_digest: str,
    ordered_front_pair_set_sha256: str,
    selected_config_index: int,
) -> None:
    """Validate issuance/config freshness before matching invocation identity."""

    validate_case_front_selection_receipt(receipt, case_scope, effective, registry)
    if (
        config_digest != receipt.config_digest
        or effective_digest != receipt.effective_digest
        or ordered_front_pair_set_sha256 != receipt.ordered_front_pair_set_sha256
        or type(selected_config_index) is not int
        or selected_config_index != receipt.selected_config_index
    ):
        _reject("front_selection_receipt_selection_mismatch")


__all__ = [
    "ManagedCaseFrontSelectionError",
    "ManagedCaseFrontSelectionReceipt",
    "check_case_front_selection",
    "validate_case_front_selection_receipt",
    "validate_receipt_matches_selection",
]
