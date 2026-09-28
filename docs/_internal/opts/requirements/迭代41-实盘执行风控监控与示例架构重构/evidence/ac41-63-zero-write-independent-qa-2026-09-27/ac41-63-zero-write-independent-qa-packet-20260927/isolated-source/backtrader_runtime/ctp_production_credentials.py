"""Protected, config-bound CTP production credential resolution.

This production-specific resolver exists for an injected, code-reviewed
runtime registry. It does not create an effective runtime, import a provider,
open a socket, or authorize production writes. The sealed production config
and exact production account/front pin must match before its private
authentication fields are copied into a redacted credential source.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from types import MappingProxyType, SimpleNamespace
from typing import Any, Dict, Mapping, Tuple

from .config import (
    CtpPrivateConfig,
    RuntimeConfig,
    require_loaded_runtime_config_seal,
)
from .credential_resolver import (
    CTP_AUTHENTICATION_CREDENTIAL_KEYS,
    CredentialResolutionError,
    RuntimeCredentialScope,
    _credential_document_values,
    _platform_name,
    _require_posix_private_config_acl,
    _require_windows_private_config_acl,
)
from .ctp_production_readonly_admission import (
    CtpProductionReadOnlyAdmissionError,
    CtpProductionReadOnlyRegistration,
    require_ctp_production_readonly_config_binding,
)
from .registry import RuntimeRegistry


class CtpProductionCredentialResolutionError(CredentialResolutionError):
    """Redacted failure resolving a protected production config credential."""


def _reject(reason: str, message: str) -> None:
    raise CtpProductionCredentialResolutionError(reason, message) from None


def _production_scope(
    config: RuntimeConfig,
    registration: CtpProductionReadOnlyRegistration,
) -> RuntimeCredentialScope:
    try:
        return RuntimeCredentialScope(
            runtime_id=registration.runtime_registration.runtime_id or "",
            strategy_id=config.strategy_id,
            provider="ctp",
            provider_environment="production",
            policy_environment="production",
            mode="live",
            preset="managed_live_direct",
            account_access="direct_provider",
            account_fingerprint_sha256=registration.account_binding_sha256,
            secrets_ref="config_yaml",
            credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
            effective_config_digest=config.config_digest,
            registration_digest=registration.runtime_registration.digest,
        )
    except Exception:
        _reject(
            "production_credential_scope_invalid",
            "the production credential scope could not be constructed",
        )
    raise AssertionError("unreachable")


def _production_private_config(
    config: RuntimeConfig,
) -> CtpPrivateConfig:
    """Return private fields from the canonical shared live CTP config."""

    canonical_live = (
        config.mode == "live"
        and config.preset == "managed_live_direct"
        and config.ctp is not None
        and config.ctp_simnow is None
        and config.ctp_production is None
        and type(config.ctp) is CtpPrivateConfig
    )
    if canonical_live:
        return config.ctp
    _reject(
        "credential_schema_mismatch",
        "sealed canonical production authentication fields are missing",
    )
    raise AssertionError("unreachable")


def _require_private_config_acl(config: RuntimeConfig, registry: RuntimeRegistry) -> None:
    """Repeat the platform private-file check before releasing credentials."""

    try:
        registration = registry.require_runtime_dir(config.strategy_dir)
        view = SimpleNamespace(registration=registration, config=config)
        platform = _platform_name()
        if platform == "nt":
            _require_windows_private_config_acl(view, registry)  # type: ignore[arg-type]
        elif platform == "posix":
            _require_posix_private_config_acl(view, registry)  # type: ignore[arg-type]
        else:
            _reject(
                "config_yaml_platform_unsupported",
                "protected production config credentials are unavailable on this platform",
            )
    except CredentialResolutionError:
        raise
    except Exception:
        _reject(
            "config_yaml_security_rejected",
            "the production config file security check failed",
        )


@dataclass(frozen=True)
class CtpProductionCredentials:
    """Resolved authentication values with an opaque, rechecked provenance seal."""

    scope: RuntimeCredentialScope
    source: str
    _values: Mapping[str, str] = field(repr=False, compare=False)
    _config: RuntimeConfig = field(repr=False, compare=False)
    _registry: RuntimeRegistry = field(repr=False, compare=False)
    _registration: CtpProductionReadOnlyRegistration = field(repr=False, compare=False)
    credentials_resolved: bool = True
    provider_connected: bool = False
    provider_session_verified: bool = False
    execution_authorized: bool = False
    external_writes_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.scope) is not RuntimeCredentialScope:
            raise ValueError("production credentials need an exact code-owned scope")
        if self.source != "config_yaml":
            raise ValueError("production CTP credentials must come from the sealed config")
        if type(self._values) not in (dict, MappingProxyType):
            raise ValueError("production credential values must be a private mapping")
        normalized = _credential_document_values({"credentials": dict(self._values)}, self.scope)
        object.__setattr__(self, "_values", normalized)
        if (
            self.credentials_resolved is not True
            or self.provider_connected is not False
            or self.provider_session_verified is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
        ):
            raise ValueError("production credential resolution cannot grant provider authority")

    def __bool__(self) -> bool:
        raise TypeError("production credentials are not provider or execution authorization")

    def __repr__(self) -> str:
        return (
            "CtpProductionCredentials(scope={!r}, source='config_yaml', "
            "provider_connected=False, provider_session_verified=False, "
            "execution_authorized=False, external_writes_authorized=False)"
        ).format(self.scope)

    @property
    def credential_names(self) -> Tuple[str, ...]:
        return self.scope.credential_keys

    def require_credential(self, name: str) -> str:
        """Return one secret only after rechecking seal, pin, and private ACL."""

        require_ctp_production_credentials_seal(
            self,
            config=self._config,
            registry=self._registry,
            admission_registration=self._registration,
        )
        if type(name) is not str or name not in self.scope.credential_keys:
            _reject("credential_name_not_available", "the requested credential is unavailable")
        try:
            return self._values[name]
        except (KeyError, TypeError):
            _reject("credential_resolution_invalid", "production credential material is invalid")
        raise AssertionError("unreachable")

    def as_public_dict(self) -> Dict[str, Any]:
        return {
            "account_scope": "redacted",
            "credential_count": len(self.scope.credential_keys),
            "credential_names": self.scope.credential_keys,
            "credentials_resolved": self.credentials_resolved,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "mode": self.scope.mode,
            "policy_environment": self.scope.policy_environment,
            "provider": self.scope.provider,
            "provider_connected": self.provider_connected,
            "provider_environment": self.scope.provider_environment,
            "provider_session_verified": self.provider_session_verified,
            "registration_digest": self.scope.registration_digest,
            "runtime_id": self.scope.runtime_id,
            "source": self.source,
            "strategy_id": self.scope.strategy_id,
        }


@dataclass(frozen=True)
class _CredentialSeal:
    registry: RuntimeRegistry
    config: RuntimeConfig
    registration: CtpProductionReadOnlyRegistration
    scope: RuntimeCredentialScope
    values: Mapping[str, str]


_CREDENTIAL_SEALS: Dict[int, Tuple[Any, _CredentialSeal]] = {}


def _seal_credentials(credentials: CtpProductionCredentials) -> CtpProductionCredentials:
    identifier = id(credentials)

    def discard(reference: Any) -> None:
        current = _CREDENTIAL_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _CREDENTIAL_SEALS.pop(identifier, None)

    reference = weakref.ref(credentials, discard)
    _CREDENTIAL_SEALS[identifier] = (
        reference,
        _CredentialSeal(
            registry=credentials._registry,
            config=credentials._config,
            registration=credentials._registration,
            scope=credentials.scope,
            values=credentials._values,
        ),
    )
    return credentials


def require_ctp_production_credentials_seal(
    credentials: CtpProductionCredentials,
    *,
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionReadOnlyRegistration,
) -> None:
    """Revalidate exact config provenance, production pin, scope, and ACL."""

    if type(credentials) is not CtpProductionCredentials:
        _reject(
            "credential_resolution_provenance_invalid",
            "credentials were not produced by the production resolver",
        )
    try:
        require_loaded_runtime_config_seal(config, registry)
        binding = require_ctp_production_readonly_config_binding(
            config, registry, admission_registration
        )
    except Exception:
        _reject(
            "production_credential_binding_rejected",
            "sealed production credentials no longer match their config pin",
        )
    expected_scope = _production_scope(config, admission_registration)
    if (
        credentials._config is not config
        or credentials._registry is not registry
        or credentials._registration is not admission_registration
        or credentials.scope != expected_scope
        or credentials.scope.account_fingerprint_sha256 != binding.account_binding_sha256
    ):
        _reject(
            "credential_resolution_provenance_invalid",
            "production credential source does not match its sealed scope",
        )
    entry = _CREDENTIAL_SEALS.get(id(credentials))
    if entry is None or entry[0]() is not credentials:
        _reject(
            "credential_resolution_provenance_invalid",
            "production credentials were not produced by the protected resolver",
        )
    seal = entry[1]
    if (
        seal.registry is not registry
        or seal.config is not config
        or seal.registration is not admission_registration
        or seal.scope != expected_scope
        or seal.values is not credentials._values
        or credentials.source != "config_yaml"
        or credentials.provider_connected is not False
        or credentials.provider_session_verified is not False
        or credentials.execution_authorized is not False
        or credentials.external_writes_authorized is not False
    ):
        _reject(
            "credential_resolution_provenance_invalid",
            "production credential source no longer matches the resolver seal",
        )
    _require_private_config_acl(config, registry)


def resolve_ctp_production_credentials(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionReadOnlyRegistration,
) -> CtpProductionCredentials:
    """Resolve only the exact auth fields from a pinned, ACL-protected config.

    The loader-sealed config must have been read through a registry whose
    registration allows the private ``config_yaml`` source. A production
    config must not be sourced from ``.env`` or from an unregistered path.
    """

    try:
        require_loaded_runtime_config_seal(config, registry)
        binding = require_ctp_production_readonly_config_binding(
            config, registry, admission_registration
        )
    except CtpProductionReadOnlyAdmissionError:
        _reject("production_credential_binding_rejected", "production config pin was rejected")
    except Exception:
        _reject("production_credential_binding_rejected", "production config pin was rejected")
    _require_private_config_acl(config, registry)
    private = _production_private_config(config)
    scope = _production_scope(config, admission_registration)
    if scope.account_fingerprint_sha256 != binding.account_binding_sha256:
        _reject("production_credential_scope_mismatch", "production credential account pin changed")
    document = {
        "credentials": {name: getattr(private, name) for name in CTP_AUTHENTICATION_CREDENTIAL_KEYS}
    }
    try:
        values = _credential_document_values(document, scope)
        credentials = CtpProductionCredentials(
            scope=scope,
            source="config_yaml",
            _values=values,
            _config=config,
            _registry=registry,
            _registration=admission_registration,
        )
    except CredentialResolutionError:
        raise
    except Exception:
        _reject("credential_document_invalid", "production authentication fields are invalid")
    return _seal_credentials(credentials)


__all__ = [
    "CtpProductionCredentialResolutionError",
    "CtpProductionCredentials",
    "require_ctp_production_credentials_seal",
    "resolve_ctp_production_credentials",
]
