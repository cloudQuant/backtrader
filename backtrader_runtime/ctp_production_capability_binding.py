"""Offline cross-package scope contract for a future CTP production writer.

This module checks that independently pinned execution, risk, and monitor
capability records all name one exact production CTP execution scope. The
records must come from a separately trusted package catalog/composition root;
this structural check does not authenticate their producer. Its result is
non-authorizing metadata and is not a write admission, provider session, or
approval decision. The module is deliberately absent from the default runtime
inventory and performs no imports of capability packages, credential access,
network I/O, or provider operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Tuple

from .ctp_production_execution_admission import CtpProductionExecutionConfigBinding


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
_REQUIRED_COMPONENTS = (
    ("execution", "bt_api_execution"),
    ("risk", "bt_api_risk"),
    ("monitor", "bt_api_monitor"),
)


class CtpProductionCapabilityBindingError(ValueError):
    """Redacted fail-closed rejection of a production capability scope bundle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


def _reject(reason: str) -> None:
    raise CtpProductionCapabilityBindingError(reason) from None


def _require_digest(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_" + name)
    return value


def _require_version(value: Any) -> str:
    if type(value) is not str or _VERSION_RE.fullmatch(value) is None:
        _reject("invalid_package_version")
    return value


def _require_component(capability: Any, package_module: Any) -> Tuple[str, str]:
    if type(capability) is not str or type(package_module) is not str:
        _reject("invalid_capability_identity")
    if (capability, package_module) not in _REQUIRED_COMPONENTS:
        _reject("unexpected_capability_identity")
    return capability, package_module


@dataclass(frozen=True)
class CtpProductionCapabilityPin:
    """Code-owned expected package and public-contract identity for one role.

    A production composition must construct these pins from its reviewed
    artifact/catalog policy. They are explicit inputs so this offline module
    cannot silently pick a package version or create a default write route.
    """

    capability: str
    package_module: str
    package_version: str
    package_artifact_sha256: str
    capability_contract_sha256: str

    def __post_init__(self) -> None:
        _require_component(self.capability, self.package_module)
        _require_version(self.package_version)
        _require_digest(self.package_artifact_sha256, "package_artifact_sha256")
        _require_digest(self.capability_contract_sha256, "capability_contract_sha256")


@dataclass(frozen=True)
class CtpProductionCapabilityBinding:
    """One package-produced capability identity bound to a CTP scope.

    ``binding_sha256`` is an opaque identity supplied by a trusted composition
    layer. This module compares it and the other claims but does not verify a
    signature, load a package, or establish that the producer is trusted.
    """

    pin: CtpProductionCapabilityPin
    binding_sha256: str
    account_binding_sha256: str = field(repr=False)
    scope_identity_sha256: str
    runtime_registration_digest: str
    execution_registration_digest: str
    config_digest: str
    effective_digest: str

    def __post_init__(self) -> None:
        if type(self.pin) is not CtpProductionCapabilityPin:
            _reject("capability_pin_required")
        CtpProductionCapabilityPin.__post_init__(self.pin)
        for name in (
            "binding_sha256",
            "account_binding_sha256",
            "scope_identity_sha256",
            "runtime_registration_digest",
            "execution_registration_digest",
            "config_digest",
            "effective_digest",
        ):
            _require_digest(getattr(self, name), name)


@dataclass(frozen=True)
class CtpProductionCapabilityBundleCheck:
    """Non-authorizing observation that three capability records share scope."""

    scope_identity_sha256: str
    runtime_registration_digest: str
    execution_registration_digest: str
    config_digest: str
    effective_digest: str
    capability_bundle_sha256: str
    required_capabilities: Tuple[str, ...] = field(
        default=("execution", "risk", "monitor"), init=False
    )
    provider_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)

    def __bool__(self) -> bool:
        raise TypeError("capability bundle check is non-authorizing scope evidence")

    def as_public_dict(self) -> dict[str, Any]:
        """Expose only redacted scope identities and fixed false authority flags."""

        return {
            "capability_bundle_sha256": self.capability_bundle_sha256,
            "cancellation_authorized": self.cancellation_authorized,
            "config_digest": self.config_digest,
            "effective_digest": self.effective_digest,
            "execution_authorized": self.execution_authorized,
            "execution_registration_digest": self.execution_registration_digest,
            "external_writes_authorized": self.external_writes_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "provider": "ctp",
            "provider_access_authorized": self.provider_access_authorized,
            "required_capabilities": self.required_capabilities,
            "runtime_registration_digest": self.runtime_registration_digest,
            "scope_identity_sha256": self.scope_identity_sha256,
        }


def _require_resolved_scope(scope: Any) -> None:
    if type(scope) is not CtpProductionExecutionConfigBinding:
        _reject("production_execution_scope_required")
    if (
        getattr(scope, "environment", None) != "production"
        or getattr(scope, "contract_verified", None) is not True
        or type(getattr(scope, "selected_front_index", None)) is not int
        or scope.selected_front_index < 0
        or type(getattr(scope, "md_front", None)) is not str
        or not scope.md_front
        or type(getattr(scope, "td_front", None)) is not str
        or not scope.td_front
    ):
        _reject("production_execution_scope_unresolved")
    if any(
        getattr(scope, name, None) is not False
        for name in (
            "provider_access_authorized",
            "credential_access_authorized",
            "execution_authorized",
            "external_writes_authorized",
            "order_submission_authorized",
            "cancellation_authorized",
            "arming_authorized",
        )
    ):
        _reject("authorizing_scope_evidence_forbidden")
    for name in (
        "account_binding_sha256",
        "scope_identity_sha256",
        "runtime_registration_digest",
        "registration_digest",
        "config_digest",
        "effective_digest",
    ):
        _require_digest(getattr(scope, name, None), name)


def _bundle_digest(
    scope: CtpProductionExecutionConfigBinding,
    bindings: Tuple[CtpProductionCapabilityBinding, ...],
) -> str:
    material = {
        "components": tuple(
            {
                "binding_sha256": binding.binding_sha256,
                "capability": binding.pin.capability,
                "capability_contract_sha256": binding.pin.capability_contract_sha256,
                "package_artifact_sha256": binding.pin.package_artifact_sha256,
                "package_module": binding.pin.package_module,
                "package_version": binding.pin.package_version,
            }
            for binding in bindings
        ),
        "scope": {
            "account_binding_sha256": scope.account_binding_sha256,
            "config_digest": scope.config_digest,
            "effective_digest": scope.effective_digest,
            "execution_registration_digest": scope.registration_digest,
            "runtime_registration_digest": scope.runtime_registration_digest,
            "scope_identity_sha256": scope.scope_identity_sha256,
        },
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        b"backtrader-ctp-production-capability-bundle-check-v1\0" + encoded.encode("ascii")
    ).hexdigest()


def validate_ctp_production_capability_bundle_binding(
    scope: CtpProductionExecutionConfigBinding,
    required_pins: Tuple[CtpProductionCapabilityPin, ...],
    capability_bindings: Tuple[CtpProductionCapabilityBinding, ...],
) -> CtpProductionCapabilityBundleCheck:
    """Validate exact execution/risk/monitor pins and their common CTP scope.

    ``required_pins`` must come from reviewed code/artifact policy, and
    ``capability_bindings`` must come from the trusted installed-capability
    catalog/composition. This function only checks their exact role, package,
    version, artifact, contract, and scope agreement. The returned value is
    structural evidence; other independently reviewed deployment, approval,
    credential, writer-fence, risk-permit, monitor-control, session, and SDK
    gates remain mandatory before any future provider writer.
    """

    _require_resolved_scope(scope)
    if type(required_pins) is not tuple or len(required_pins) != len(_REQUIRED_COMPONENTS):
        _reject("exact_capability_pins_required")
    if type(capability_bindings) is not tuple or len(capability_bindings) != len(
        _REQUIRED_COMPONENTS
    ):
        _reject("exact_capability_bindings_required")

    for index, (capability, package_module) in enumerate(_REQUIRED_COMPONENTS):
        pin = required_pins[index]
        binding = capability_bindings[index]
        if type(pin) is not CtpProductionCapabilityPin:
            _reject("capability_pin_required")
        CtpProductionCapabilityPin.__post_init__(pin)
        if (pin.capability, pin.package_module) != (capability, package_module):
            _reject("capability_pin_set_mismatch")
        if type(binding) is not CtpProductionCapabilityBinding:
            _reject("capability_binding_required")
        CtpProductionCapabilityBinding.__post_init__(binding)
        if binding.pin != pin:
            _reject("capability_binding_pin_mismatch")
        if (
            binding.account_binding_sha256 != scope.account_binding_sha256
            or binding.scope_identity_sha256 != scope.scope_identity_sha256
            or binding.runtime_registration_digest != scope.runtime_registration_digest
            or binding.execution_registration_digest != scope.registration_digest
            or binding.config_digest != scope.config_digest
            or binding.effective_digest != scope.effective_digest
        ):
            _reject("capability_scope_mismatch")

    return CtpProductionCapabilityBundleCheck(
        scope_identity_sha256=scope.scope_identity_sha256,
        runtime_registration_digest=scope.runtime_registration_digest,
        execution_registration_digest=scope.registration_digest,
        config_digest=scope.config_digest,
        effective_digest=scope.effective_digest,
        capability_bundle_sha256=_bundle_digest(scope, capability_bindings),
    )


__all__ = [
    "CtpProductionCapabilityBinding",
    "CtpProductionCapabilityBindingError",
    "CtpProductionCapabilityBundleCheck",
    "CtpProductionCapabilityPin",
    "validate_ctp_production_capability_bundle_binding",
]
