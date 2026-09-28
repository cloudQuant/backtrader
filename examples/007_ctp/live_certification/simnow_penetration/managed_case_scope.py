"""Bind a staged certification case to the sealed 007 CTP read-only runtime.

The returned scope is diagnostic provenance only. It does not authorize a
provider session, subscription, order, cancel, or certification PASS.
"""

from __future__ import annotations

import hashlib
import json
import re
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from backtrader_runtime.ctp_sandbox_readonly_admission import (
    require_ctp_sandbox_profile_runtime,
)
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
)
from backtrader_runtime.registry import EffectiveRuntimeConfig, RuntimeRegistry

from . import managed_case_entry
from .common.case_engine import DescriptiveCasePlan, load_descriptive_case_plan
from .common.decision_engine import DecisionScope


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT_IDENTITY_SCHEME = "ctp.simnow.broker-user.sha256.v1"
_ACCOUNT_IDENTITY_DOMAIN = b"backtrader.iteration41.007.account-identity\x00"
_ISSUED_SCOPE_REFS: dict[int, weakref.ReferenceType["CertificationCaseScope"]] = {}


@dataclass(frozen=True)
class CertificationCaseScope:
    """Non-authorizing identities for one real-case execution candidate."""

    case_id: str
    scenario_id: str
    runtime_id: str
    account_identity_scheme: str
    account_identity_sha256: str
    suite_config_digest: str
    suite_effective_digest: str
    case_config_digest: str
    strategy_plan_digest: str
    runner_digest: str


class CertificationCaseScopeError(ValueError):
    """Redacted case/runtime binding failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _reject(reason: str) -> NoReturn:
    raise CertificationCaseScopeError(reason)


def _account_identity_sha256(effective: EffectiveRuntimeConfig) -> str:
    """Derive a pseudonymous account key from the already-sealed private config."""

    try:
        private = effective.config.ctp_simnow
        broker_id = private.broker_id
        user_id = private.user_id
        if (
            type(broker_id) is not str
            or not broker_id
            or broker_id != broker_id.strip()
            or "\x00" in broker_id
            or type(user_id) is not str
            or not user_id
            or user_id != user_id.strip()
            or "\x00" in user_id
        ):
            _reject("certification_account_identity_invalid")
        canonical = json.dumps(
            [ACCOUNT_IDENTITY_SCHEME, broker_id, user_id],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(_ACCOUNT_IDENTITY_DOMAIN + canonical).hexdigest()
    except CertificationCaseScopeError:
        raise
    except Exception:
        _reject("certification_account_identity_invalid")


def _remember_issued_scope(scope: CertificationCaseScope) -> None:
    """Track exact binder-issued objects to reject replaced/hand-built scopes."""

    identity = id(scope)

    def discard(reference: weakref.ReferenceType[CertificationCaseScope]) -> None:
        if _ISSUED_SCOPE_REFS.get(identity) is reference:
            _ISSUED_SCOPE_REFS.pop(identity, None)

    _ISSUED_SCOPE_REFS[identity] = weakref.ref(scope, discard)


def _is_issued_scope(scope: CertificationCaseScope) -> bool:
    reference = _ISSUED_SCOPE_REFS.get(id(scope))
    return reference is not None and reference() is scope


def _bind_case_scope(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    case_id: str,
    case_file: object,
    *,
    expected_runtime_dir: Path,
) -> CertificationCaseScope:
    """Shared binder; the public entry fixes the code-owned 007 directory."""

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("sealed_ctp_runtime_required")
    try:
        require_ctp_sandbox_profile_runtime(effective, registry)
        registration = registry.require_runtime_dir(expected_runtime_dir)
    except Exception:
        _reject("sealed_ctp_runtime_required")
    if (
        registration is not effective.registration
        or registration.runtime_dir != expected_runtime_dir
        or registration.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
        or registration.strategy_id != ITERATION41_007_CTP_PRIVATE_STRATEGY_ID
        or effective.strategy_id != ITERATION41_007_CTP_PRIVATE_STRATEGY_ID
    ):
        _reject("certification_runtime_mismatch")

    try:
        scenarios = managed_case_entry._load_code_owned_scenarios()
    except Exception:
        _reject("certification_scenarios_invalid")
    if type(case_id) is not str or case_id not in scenarios:
        _reject("certification_case_id_invalid")
    if not managed_case_entry._is_exact_direct_case_path(case_id, case_file):
        _reject("certification_case_path_invalid")
    try:
        runner_digest = hashlib.sha256(
            managed_case_entry._expected_script(case_id).read_bytes()
        ).hexdigest()
    except (OSError, RuntimeError, ValueError):
        _reject("certification_case_path_invalid")
    try:
        case_digest = managed_case_entry._validated_case_config_digest(
            managed_case_entry._expected_script(case_id), case_id
        )
    except Exception:
        _reject("certification_case_config_invalid")
    if case_digest is None:
        _reject("certification_case_config_invalid")

    strategy_path = managed_case_entry._expected_script(case_id).parent / f"{case_id}_strategy.py"
    try:
        if strategy_path.is_symlink() or not strategy_path.is_file():
            _reject("certification_strategy_plan_invalid")
        plan = load_descriptive_case_plan(
            strategy_path,
            expected_case_id=case_id,
            expected_scenario_id=scenarios[case_id].scenario_id,
        )
    except Exception:
        _reject("certification_strategy_plan_invalid")

    account_identity_sha256 = _account_identity_sha256(effective)
    scope = CertificationCaseScope(
        case_id=case_id,
        scenario_id=scenarios[case_id].scenario_id,
        runtime_id=registration.runtime_id,
        account_identity_scheme=ACCOUNT_IDENTITY_SCHEME,
        account_identity_sha256=account_identity_sha256,
        suite_config_digest=effective.config_digest,
        suite_effective_digest=effective.effective_digest,
        case_config_digest=case_digest,
        strategy_plan_digest=plan.source_sha256,
        runner_digest=runner_digest,
    )
    _remember_issued_scope(scope)
    return scope


def bind_case_scope(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    case_id: str,
    case_file: object,
) -> CertificationCaseScope:
    """Bind one case to the exact 007 suite root; confer no I/O authority."""

    return _bind_case_scope(
        effective,
        registry,
        case_id,
        case_file,
        expected_runtime_dir=ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
    )


def decision_scope_from_case_scope(
    scope: CertificationCaseScope, plan: DescriptiveCasePlan
) -> DecisionScope:
    """Bind the typed review engine to a previously sealed diagnostic scope.

    Only the exact case-scope object issued by the sealed binder in this
    process is accepted. This object-identity check is not provider
    authentication and grants no dispatch or certification authority.
    """

    if type(scope) is not CertificationCaseScope or type(plan) is not DescriptiveCasePlan:
        _reject("certification_decision_scope_invalid")
    if not _is_issued_scope(scope):
        _reject("certification_decision_scope_invalid")
    try:
        scenario = managed_case_entry._load_code_owned_scenarios()[scope.case_id]
    except (KeyError, ValueError):
        _reject("certification_decision_scope_invalid")
    if (
        scope.scenario_id != scenario.scenario_id
        or scope.runtime_id != ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
        or scope.account_identity_scheme != ACCOUNT_IDENTITY_SCHEME
        or type(scope.account_identity_sha256) is not str
        or _SHA256_RE.fullmatch(scope.account_identity_sha256) is None
        or plan.case_id != scope.case_id
        or plan.source_sha256 != scope.strategy_plan_digest
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in (
                scope.suite_config_digest,
                scope.suite_effective_digest,
                scope.case_config_digest,
                scope.strategy_plan_digest,
                scope.runner_digest,
            )
        )
    ):
        _reject("certification_decision_scope_invalid")
    payload = {
        "schema": "simnow.certification.case-scope.v2",
        "case_id": scope.case_id,
        "scenario_id": scope.scenario_id,
        "runtime_id": scope.runtime_id,
        "account_identity_scheme": scope.account_identity_scheme,
        "account_identity_sha256": scope.account_identity_sha256,
        "suite_config_digest": scope.suite_config_digest,
        "suite_effective_digest": scope.suite_effective_digest,
        "case_config_digest": scope.case_config_digest,
        "strategy_plan_digest": scope.strategy_plan_digest,
        "runner_digest": scope.runner_digest,
    }
    scope_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    ).hexdigest()
    result = DecisionScope(
        scope.case_id,
        scope.scenario_id,
        plan.source_sha256,
        scope_sha256,
        scope.account_identity_sha256,
    )
    result.validate(plan)
    return result


__all__ = [
    "ACCOUNT_IDENTITY_SCHEME",
    "CertificationCaseScope",
    "CertificationCaseScopeError",
    "bind_case_scope",
    "decision_scope_from_case_scope",
]
