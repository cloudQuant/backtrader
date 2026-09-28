"""Config-first CTP SimNow private-account read-only admission.

This is a narrow prerequisite boundary for one code-owned CTP SimNow
private-account observation.  It does not resolve credentials, import an SDK,
create a default factory, or grant any execution authority.  A composition
root must supply the reviewed registration and an injected
:class:`CtpReadOnlySessionFactory` only after the runtime config has been
sealed against the exact registry.

The factory receives the existing CTP read-only session request and must be
constructed with the same reviewed registration. Its SDK adapter uses the
exact configured front pair, neutral code-owned SimNow scope marker, and
instrument/exchange/hedge scope captured here. No set/profile is inferred from
the addresses. Environment variables and credentials cannot override them.
This admission never grants write authority.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

from .ctp_preflight import (
    CTP_PROVIDER,
    CtpReadOnlyQuerySnapshot,
    CtpReadOnlySession,
    CtpReadOnlySessionFactory,
    CtpReadOnlySessionIdentity,
    CtpReadOnlySessionRequest,
)
from .errors import RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
)


_CTP_SIMNOW_ENVIRONMENT_RE = re.compile(r"^simnow(?:_set([12]))?$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_PROFILE_RE = re.compile(r"^(?:config_front_pair|set([12])_[a-z0-9_]{1,63})$")
_CTP_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CTP_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_CTP_HEDGE_RE = re.compile(r"^[1-3]$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONFIGURED_SIMNOW_PROFILE = "config_front_pair"


class CtpSandboxReadOnlyAdmissionError(ValueError):
    """Redacted fail-closed rejection for the sandbox read-only boundary."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpSandboxReadOnlyAdmissionError(reason, message)


def _sha256(value: Any, field_name: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _reject("invalid_digest", "invalid {0}".format(field_name))
    return value


def _identifier(value: Any, field_name: str) -> str:
    if type(value) is not str or value != value.strip() or not _IDENTIFIER_RE.fullmatch(value):
        _reject("invalid_registration", "invalid {0}".format(field_name))
    return value


def _secrets_ref(value: Any) -> str:
    if (
        type(value) is not str
        or value == "none"
        or value != value.strip()
        or not value
        or len(value) > 256
        or any(character.isspace() for character in value)
    ):
        _reject("invalid_registration", "invalid allowed secrets reference")
    return value


def _environment_and_profile(environment: Any, sdk_profile: Any) -> tuple[str, str]:
    if (
        type(environment) is not str
        or environment != environment.strip()
        or (environment_match := _CTP_SIMNOW_ENVIRONMENT_RE.fullmatch(environment)) is None
    ):
        _reject(
            "environment_not_simnow", "CTP sandbox admission requires an exact SimNow environment"
        )
    if type(sdk_profile) is not str or sdk_profile != sdk_profile.strip():
        _reject("invalid_registration", "invalid CTP SDK profile")
    profile_match = _PROFILE_RE.fullmatch(sdk_profile)
    if profile_match is None:
        _reject("invalid_registration", "invalid CTP SDK profile")
    environment_group = environment_match.group(1)
    profile_group = profile_match.group(1)
    if environment == "simnow":
        if sdk_profile != _CONFIGURED_SIMNOW_PROFILE:
            _reject(
                "environment_profile_mismatch",
                "configured SimNow fronts require the direct-pair SDK marker",
            )
    elif profile_group != environment_group:
        _reject(
            "environment_profile_mismatch",
            "CTP SDK profile does not match the registered SimNow environment",
        )
    return environment, sdk_profile


def _ctp_front(value: Any, field_name: str) -> str:
    """Validate a canonical TCP front without classifying or replacing it."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        _reject("invalid_registration", "invalid CTP {0}".format(field_name))
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _reject("invalid_registration", "invalid CTP {0}".format(field_name))
    if (
        parsed.scheme != "tcp"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or value != "tcp://{0}:{1}".format(parsed.hostname, port)
    ):
        _reject("invalid_registration", "invalid CTP {0}".format(field_name))
    return value


def _native_query_scope(
    instrument_id: Any,
    exchange_id: Any,
    hedge_flag: Any,
    *,
    reason: str,
) -> tuple[str, str, str]:
    """Validate the bounded native CTP query scope outside operator config."""

    instrument_id = _identifier(instrument_id, "instrument_id")
    exchange_id = _identifier(exchange_id, "exchange_id")
    hedge_flag = _identifier(hedge_flag, "hedge_flag")
    if not _CTP_INSTRUMENT_RE.fullmatch(instrument_id):
        _reject(reason, "invalid instrument_id")
    if not _CTP_EXCHANGE_RE.fullmatch(exchange_id):
        _reject(reason, "invalid exchange_id")
    if not _CTP_HEDGE_RE.fullmatch(hedge_flag):
        _reject(reason, "invalid hedge_flag")
    return instrument_id, exchange_id, hedge_flag


def _session_ttl(value: Any) -> float:
    if type(value) not in (int, float):
        _reject("invalid_registration", "invalid read-only session TTL")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_registration", "invalid read-only session TTL")
    if not math.isfinite(normalized) or normalized <= 0.0 or normalized > 300.0:
        _reject("invalid_registration", "invalid read-only session TTL")
    return normalized


def _timestamp(value: Any, field_name: str) -> float:
    if type(value) not in (int, float):
        _reject("invalid_clock", "invalid {0}".format(field_name))
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_clock", "invalid {0}".format(field_name))
    if not math.isfinite(normalized):
        _reject("invalid_clock", "invalid {0}".format(field_name))
    return 0.0 if normalized == 0.0 else normalized


@dataclass(frozen=True)
class CtpSandboxReadOnlyRegistration:
    """One exact CTP private-read route and query scope.

    ``runtime_registration`` must be the same object registered in the trusted
    registry. A static binding may set the scope in code; the restricted
    config-driven binding derives it only from one sealed private SimNow
    ``simulation/sandbox`` config. The exact TD/MD strings are preserved as
    configured; this contract does not classify them by set or SDK profile.
    The resulting admission always binds one exact scope and grants no write.
    """

    runtime_registration: RegisteredRuntime
    environment: str
    sdk_profile: str
    account_fingerprint_sha256: str = field(repr=False)
    allowed_secrets_ref: str
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    td_front: str
    md_front: str
    session_ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        if type(self.runtime_registration) is not RegisteredRuntime:
            _reject("invalid_registration", "invalid registered runtime binding")
        environment, sdk_profile = _environment_and_profile(self.environment, self.sdk_profile)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "sdk_profile", sdk_profile)
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(self, "allowed_secrets_ref", _secrets_ref(self.allowed_secrets_ref))
        instrument_id, exchange_id, hedge_flag = _native_query_scope(
            self.instrument_id,
            self.exchange_id,
            self.hedge_flag,
            reason="invalid_registration",
        )
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "exchange_id", exchange_id)
        object.__setattr__(self, "hedge_flag", hedge_flag)
        object.__setattr__(self, "td_front", _ctp_front(self.td_front, "td_front"))
        object.__setattr__(self, "md_front", _ctp_front(self.md_front, "md_front"))
        object.__setattr__(self, "session_ttl_seconds", _session_ttl(self.session_ttl_seconds))


@dataclass(frozen=True)
class CtpSandboxReadOnlyObservation:
    """Digest-only private read evidence that cannot act as account authority.

    A native-certificate digest, when the shared snapshot contract carries
    one, remains unverified metadata at this boundary.  It cannot establish
    SDK issuance, account acceptance, or execution authority.
    """

    runtime_id: str
    strategy_id: str
    effective_config_digest: str
    registration_digest: str
    provider: str
    environment: str
    sdk_profile: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    trading_day: str
    connection_generation: int
    query_snapshot: CtpReadOnlyQuerySnapshot
    native_certificate_sha256: Optional[str] = None
    native_certificate_provenance: str = "LOCAL_ONLY"
    read_only_route_admitted: bool = True
    session_connected: bool = True
    provider_preflight_started: bool = False
    approval_required: bool = False
    account_acceptance_established: bool = False
    execution_authorized: bool = False
    external_writes_authorized: bool = False
    order_submission_authorized: bool = False
    cancellation_authorized: bool = False
    settlement_authorized: bool = False
    arming_authorized: bool = False
    external_write_requests: int = 0

    def __post_init__(self) -> None:
        runtime_id = _identifier(self.runtime_id, "runtime_id")
        strategy_id = _identifier(self.strategy_id, "strategy_id")
        effective_config_digest = _sha256(self.effective_config_digest, "effective_config_digest")
        registration_digest = _sha256(self.registration_digest, "registration_digest")
        if self.provider != CTP_PROVIDER:
            _reject("provider_not_ctp", "CTP sandbox admission requires provider ctp")
        environment, sdk_profile = _environment_and_profile(self.environment, self.sdk_profile)
        account_fingerprint = _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256")
        instrument_id, exchange_id, hedge_flag = _native_query_scope(
            self.instrument_id,
            self.exchange_id,
            self.hedge_flag,
            reason="invalid_observation",
        )
        identity = _normalise_identity(
            CtpReadOnlySessionIdentity(
                provider=self.provider,
                environment=environment,
                account_fingerprint_sha256=account_fingerprint,
                trading_day=self.trading_day,
                connection_generation=self.connection_generation,
            ),
            "observation identity",
        )
        snapshot = _normalise_snapshot(self.query_snapshot)
        if snapshot.identity != identity:
            _reject(
                "snapshot_identity_mismatch", "CTP query snapshot identity does not match session"
            )
        native_certificate_sha256 = _snapshot_native_certificate_sha256(snapshot)
        # A snapshot digest alone is not proof of SDK-native issuance: an
        # injected fake session can manufacture a SHA-256-shaped value.  Only
        # a future typed builder/factory composition root can make that claim.
        expected_native_certificate_provenance = (
            "UNVERIFIED_DIGEST_ONLY" if native_certificate_sha256 is not None else "LOCAL_ONLY"
        )
        if (
            self.native_certificate_sha256 != native_certificate_sha256
            or self.native_certificate_provenance != expected_native_certificate_provenance
        ):
            _reject(
                "invalid_observation",
                "native certificate provenance must be derived from the query snapshot",
            )
        if (
            self.read_only_route_admitted is not True
            or self.session_connected is not True
            or self.provider_preflight_started is not False
            or self.approval_required is not False
            or self.account_acceptance_established is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
            or self.order_submission_authorized is not False
            or self.cancellation_authorized is not False
            or self.settlement_authorized is not False
            or self.arming_authorized is not False
            or type(self.external_write_requests) is not int
            or self.external_write_requests != 0
        ):
            _reject("invalid_observation", "CTP sandbox observation cannot grant authority")
        object.__setattr__(self, "runtime_id", runtime_id)
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "effective_config_digest", effective_config_digest)
        object.__setattr__(self, "registration_digest", registration_digest)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "sdk_profile", sdk_profile)
        object.__setattr__(self, "account_fingerprint_sha256", account_fingerprint)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "exchange_id", exchange_id)
        object.__setattr__(self, "hedge_flag", hedge_flag)
        object.__setattr__(self, "trading_day", identity.trading_day)
        object.__setattr__(self, "connection_generation", identity.connection_generation)
        object.__setattr__(self, "query_snapshot", snapshot)
        object.__setattr__(self, "native_certificate_sha256", native_certificate_sha256)
        object.__setattr__(
            self,
            "native_certificate_provenance",
            expected_native_certificate_provenance,
        )

    def __bool__(self) -> bool:
        raise TypeError(
            "CtpSandboxReadOnlyObservation is a non-authority read-only observation; "
            "do not use it as account acceptance"
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return the read-only route without a reversible account hash."""

        return {
            "account_acceptance_established": self.account_acceptance_established,
            "account_scope": "redacted",
            "approval_required": self.approval_required,
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "connection_generation": self.connection_generation,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "exchange_id": self.exchange_id,
            "execution_authorized": self.execution_authorized,
            "external_write_requests": self.external_write_requests,
            "external_writes_authorized": self.external_writes_authorized,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "native_certificate_provenance": self.native_certificate_provenance,
            "native_certificate_sha256": self.native_certificate_sha256,
            "order_submission_authorized": self.order_submission_authorized,
            "provider": self.provider,
            "provider_preflight_started": self.provider_preflight_started,
            "query_snapshot": self.query_snapshot.as_public_dict(),
            "read_only_route_admitted": self.read_only_route_admitted,
            "registration_digest": self.registration_digest,
            "runtime_id": self.runtime_id,
            "sdk_profile": self.sdk_profile,
            "session_connected": self.session_connected,
            "settlement_authorized": self.settlement_authorized,
            "strategy_id": self.strategy_id,
            "trading_day": self.trading_day,
        }


def _normalise_registration(value: Any) -> CtpSandboxReadOnlyRegistration:
    if type(value) is not CtpSandboxReadOnlyRegistration:
        _reject("registration_required", "a code-owned CTP sandbox registration is required")
    try:
        return CtpSandboxReadOnlyRegistration(
            runtime_registration=value.runtime_registration,
            environment=value.environment,
            sdk_profile=value.sdk_profile,
            account_fingerprint_sha256=value.account_fingerprint_sha256,
            allowed_secrets_ref=value.allowed_secrets_ref,
            instrument_id=value.instrument_id,
            exchange_id=value.exchange_id,
            hedge_flag=value.hedge_flag,
            td_front=value.td_front,
            md_front=value.md_front,
            session_ttl_seconds=value.session_ttl_seconds,
        )
    except CtpSandboxReadOnlyAdmissionError:
        raise
    except Exception:
        _reject("invalid_registration", "invalid code-owned CTP sandbox registration")


def _normalise_identity(value: Any, field_name: str) -> CtpReadOnlySessionIdentity:
    if type(value) is not CtpReadOnlySessionIdentity:
        _reject("invalid_session_identity", "invalid {0}".format(field_name))
    try:
        return CtpReadOnlySessionIdentity(
            provider=value.provider,
            environment=value.environment,
            account_fingerprint_sha256=value.account_fingerprint_sha256,
            trading_day=value.trading_day,
            connection_generation=value.connection_generation,
        )
    except Exception:
        _reject("invalid_session_identity", "invalid {0}".format(field_name))


def _normalise_snapshot(value: Any) -> CtpReadOnlyQuerySnapshot:
    if type(value) is not CtpReadOnlyQuerySnapshot:
        _reject("invalid_query_snapshot", "invalid CTP query snapshot")
    try:
        normalized_fields = getattr(CtpReadOnlyQuerySnapshot, "__dataclass_fields__", {})
        arguments = {
            "identity": value.identity,
            "query_digests": value.query_digests,
            "snapshot_sha256": value.snapshot_sha256,
        }
        # The reusable CTP contract starts as a local digest-only snapshot.
        # A later SDK-backed extension may add a typed native-certificate
        # digest. Preserve it only when it is part of that shared contract;
        # this boundary still treats it as unverified because it does not
        # establish factory provenance or SDK issuance on its own.
        if "native_certificate_sha256" in normalized_fields:
            arguments["native_certificate_sha256"] = getattr(
                value, "native_certificate_sha256", None
            )
        if "rate_exchange_scopes" in normalized_fields:
            arguments["rate_exchange_scopes"] = getattr(value, "rate_exchange_scopes", ())
        return CtpReadOnlyQuerySnapshot(**arguments)
    except Exception:
        _reject("invalid_query_snapshot", "invalid CTP query snapshot")


def _snapshot_native_certificate_sha256(snapshot: CtpReadOnlyQuerySnapshot) -> Optional[str]:
    """Read optional native provenance only from the shared snapshot contract."""

    if "native_certificate_sha256" not in getattr(
        CtpReadOnlyQuerySnapshot, "__dataclass_fields__", {}
    ):
        return None
    try:
        native_certificate_sha256 = snapshot.native_certificate_sha256
    except Exception:
        _reject("invalid_query_snapshot", "invalid native CTP certificate provenance")
    if native_certificate_sha256 is None:
        return None
    return _sha256(native_certificate_sha256, "native_certificate_sha256")


def _require_session_deadline(valid_until: float, monotonic_deadline: float) -> None:
    if (
        _timestamp(time.time(), "now") >= valid_until
        or _timestamp(time.monotonic(), "monotonic_now") >= monotonic_deadline
    ):
        _reject("session_deadline_expired", "CTP sandbox read-only session deadline has expired")


def require_ctp_sandbox_profile_registration(
    registration: RegisteredRuntime,
    registry: RuntimeRegistry,
) -> RuntimeProfile:
    """Return the CTP sandbox profile eligible for this read-only preflight.

    The current preflight accepts one complete zero-write
    ``simulation/sandbox`` profile tied to a code-owned config-driven CTP
    binding. Any future change to profile capabilities needs its own reviewed
    policy and dispatcher contract.
    """

    if type(registration) is not RegisteredRuntime or type(registry) is not RuntimeRegistry:
        _reject("runtime_profile_mismatch", "registered CTP sandbox profile is invalid")
    profiles = registration.profiles
    profile = registration.profile_for("simulation", "sandbox")
    unavailable = tuple(
        (item.mode, item.preset, item.reason) for item in registration.unavailable_mode_profiles
    )
    if (
        len(profiles) != 1
        or type(profile) is not RuntimeProfile
        or profiles[0] is not profile
        or profile.mode != "simulation"
        or profile.preset != "sandbox"
        or registration.allowed_presets != ()
        or registration.allowed_parameter_keys != ()
        or registration.allowed_secrets_refs != ("none",)
        or registration.available_capabilities != ()
        or registration.offline_managed_execution is not False
        or registration.sandbox_write_policy != "deny"
        or registration.approval_receipt_digest is not None
        or registration.runner_module is not None
        or registration.runner_entrypoint != "run_runtime"
        or registration.capability_modules != ()
        or registration.bootstrap_parameters != ()
        or profile.allowed_parameter_keys != ()
        or profile.allowed_secrets_refs != ("config_yaml",)
        or profile.available_capabilities != ()
        or profile.approval_receipt_digest is not None
        or profile.runner_module is not None
        or profile.runner_entrypoint != "run_runtime"
        or profile.capability_modules != ()
        or profile.offline_managed_execution is not False
        or profile.sandbox_write_policy != "deny"
        or unavailable
        != (("live", "managed_live_direct", "managed_live_direct_profile_unavailable"),)
    ):
        _reject(
            "runtime_profile_mismatch",
            "registered profile is not the exact zero-write CTP sandbox route",
        )
    try:
        resolved = registry.require_runtime_dir(registration.runtime_dir)
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
    except Exception:
        _reject("runtime_profile_mismatch", "registered CTP sandbox profile is unavailable")
    # Import locally to avoid making the admission module depend on the
    # operator composition at import time.
    from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding

    if (
        resolved is not registration
        or type(binding) is not CtpSimNowConfigReadOnlyBinding
        or binding.runtime_id != registration.runtime_id
    ):
        _reject(
            "runtime_profile_mismatch",
            "registered profile is not bound to CTP config-driven read-only dispatch",
        )
    return profile


def require_ctp_sandbox_profile_runtime(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> RuntimeProfile:
    """Validate a sealed config against the exact profile preflight exception."""

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        _reject("effective_config_required", "a sealed CTP runtime configuration is required")
    try:
        require_effective_runtime_config_seal(effective, registry)
    except Exception:
        _reject("effective_config_mismatch", "sealed runtime configuration does not match registry")
    profile = require_ctp_sandbox_profile_registration(effective.registration, registry)
    from .config import CtpSimNowPrivateConfig

    private = effective.config.ctp_simnow
    if (
        effective.profile is not profile
        or effective.mode != "simulation"
        or effective.preset != "sandbox"
        or effective.config.strategy_id != effective.registration.strategy_id
        or effective.config.secrets_ref != "config_yaml"
        or type(private) is not CtpSimNowPrivateConfig
        or type(private.front_pairs) is not tuple
        or not private.front_pairs
        or len(private.front_pairs) > 8
        or tuple(effective.parameters) != ()
        or effective.policy.name != "sandbox"
        or effective.policy.mode != "simulation"
        or effective.policy.environment != "sandbox"
        or effective.order_route is not None
        or effective.account_access != "sandbox_private_read"
        or effective.required_capabilities != ()
        or effective.allows_network is not True
        or effective.allows_external_writes is not False
        or effective.allows_production_writes is not False
        or effective.allows_hypothetical_fills is not False
        or effective.requires_approval is not False
        or effective.requires_live_confirmation is not False
    ):
        _reject("runtime_profile_mismatch", "sealed runtime is not the exact CTP sandbox profile")
    return profile


def _require_runtime_contract(
    effective: Any,
    registry: Any,
    admission_registration: Any,
) -> tuple[EffectiveRuntimeConfig, RuntimeRegistry, CtpSandboxReadOnlyRegistration]:
    """Verify all sealed config and code-owned static constraints before I/O."""

    if type(effective) is not EffectiveRuntimeConfig:
        _reject("effective_config_required", "a sealed effective runtime configuration is required")
    if type(registry) is not RuntimeRegistry:
        _reject("registry_required", "a trusted runtime registry is required")
    try:
        require_effective_runtime_config_seal(effective, registry)
    except RuntimeConfigError:
        _reject("effective_config_mismatch", "sealed runtime configuration does not match registry")
    except Exception:
        _reject("effective_config_mismatch", "sealed runtime configuration does not match registry")

    admission = _normalise_registration(admission_registration)
    try:
        registered = registry.require_runtime_dir(effective.config.strategy_dir)
    except Exception:
        _reject("runtime_registration_mismatch", "registered runtime cannot be resolved")
    if registered is not effective.registration or registered is not admission.runtime_registration:
        _reject(
            "runtime_registration_mismatch",
            "sealed runtime does not match the code-owned CTP registration",
        )
    if effective.profile is None:
        # Keep the established legacy binding unchanged.  Profile-backed
        # runtimes have inert legacy fields, so their selected profile is
        # validated separately below rather than inheriting from these fields.
        if (
            registered.profiles
            or registered.allowed_presets != ("sandbox",)
            or registered.allowed_parameter_keys != ()
            or registered.allowed_secrets_refs != (admission.allowed_secrets_ref,)
            or registered.sandbox_write_policy != "deny"
            or registered.approval_receipt_digest is not None
            or registered.available_capabilities != ()
            or registered.offline_managed_execution is not False
        ):
            _reject(
                "runtime_policy_mismatch",
                "registered runtime is not the exact zero-write CTP sandbox route",
            )
    else:
        require_ctp_sandbox_profile_runtime(effective, registry)
        if admission.allowed_secrets_ref != "config_yaml":
            _reject(
                "runtime_policy_mismatch",
                "profile-backed CTP sandbox reads require config_yaml credentials",
            )
        private = effective.config.ctp_simnow
        try:
            configured_pairs = tuple(
                (pair["td_front"], pair["md_front"]) for pair in private.front_pairs
            )
        except Exception:
            _reject("runtime_policy_mismatch", "sealed CTP profile has no exact front pair")
        configured_account = hashlib.sha256(
            "{0}:{1}".format(private.broker_id, private.user_id).encode("utf-8")
        ).hexdigest()
        if (
            admission.environment != "simnow"
            or admission.sdk_profile != _CONFIGURED_SIMNOW_PROFILE
            or (admission.td_front, admission.md_front) not in configured_pairs
            or admission.instrument_id != private.instrument_id
            or admission.exchange_id != private.exchange_id
            or admission.hedge_flag != private.hedge_flag
            or not hmac.compare_digest(
                admission.account_fingerprint_sha256,
                configured_account,
            )
        ):
            _reject(
                "runtime_policy_mismatch",
                "CTP profile admission does not match the sealed config scope",
            )
    if (
        effective.config.strategy_id != registered.strategy_id
        or effective.config.secrets_ref != admission.allowed_secrets_ref
        or tuple(effective.parameters) != ()
        or effective.mode != "simulation"
        or effective.preset != "sandbox"
        or effective.policy.name != "sandbox"
        or effective.policy.mode != "simulation"
        or effective.policy.environment != "sandbox"
        or effective.order_route is not None
        or effective.account_access != "sandbox_private_read"
        or effective.required_capabilities != ()
        or effective.allows_network is not True
        or effective.allows_external_writes is not False
        or effective.allows_production_writes is not False
        or effective.allows_hypothetical_fills is not False
        or effective.requires_approval is not False
        or effective.requires_live_confirmation is not False
    ):
        _reject(
            "runtime_policy_mismatch",
            "sealed runtime is not the exact zero-write CTP sandbox route",
        )
    return effective, registry, admission


def _matching_identity(
    request: CtpReadOnlySessionRequest,
    identity: CtpReadOnlySessionIdentity,
) -> bool:
    return (
        identity.provider == request.provider
        and identity.environment == request.environment
        and hmac.compare_digest(
            identity.account_fingerprint_sha256, request.account_fingerprint_sha256
        )
    )


def require_ctp_sandbox_readonly_runtime_contract(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
) -> CtpSandboxReadOnlyRegistration:
    """Validate the sealed zero-write route before resolving secrets or an SDK.

    This is the composition-root extension point for constructing an injected
    ``CtpReadOnlySessionFactory``.  It has no access to a session factory,
    secret resolver, provider client, or SDK.  The reused runtime seal does
    retain its required local directory-identity check before any caller can
    resolve credentials or start a provider session.
    """

    _effective, _registry, admission = _require_runtime_contract(
        effective,
        registry,
        admission_registration,
    )
    del _effective, _registry
    return admission


def admit_ctp_simnow_sandbox_readonly(
    *,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    session_factory: Optional[CtpReadOnlySessionFactory] = None,
) -> CtpSandboxReadOnlyObservation:
    """Observe one exact CTP SimNow private account through a zero-write route.

    This function verifies the sealed runtime, exact registered secret route,
    CTP SimNow environment, account fingerprint, and code-owned native-query
    scope before it reads an attribute from ``session_factory``.  Its result
    is deliberately not account acceptance, provider approval, or authority
    to submit, cancel, settle, arm, or write externally.
    """

    admission = require_ctp_sandbox_readonly_runtime_contract(
        effective,
        registry,
        admission_registration,
    )
    now = _timestamp(time.time(), "now")
    valid_until = now + admission.session_ttl_seconds
    monotonic_deadline = (
        _timestamp(time.monotonic(), "monotonic_now") + admission.session_ttl_seconds
    )
    request = CtpReadOnlySessionRequest(
        provider=CTP_PROVIDER,
        environment=admission.environment,
        account_fingerprint_sha256=admission.account_fingerprint_sha256,
        valid_until=valid_until,
    )
    _require_session_deadline(request.valid_until, monotonic_deadline)
    if session_factory is None:
        _reject(
            "session_factory_required",
            "CTP sandbox admission requires an injected read-only factory",
        )
    try:
        open_read_only = getattr(session_factory, "open_read_only", None)
    except Exception:
        _reject("invalid_session_factory", "invalid CTP read-only session factory")
    if not callable(open_read_only):
        _reject("invalid_session_factory", "invalid CTP read-only session factory")

    try:
        session: Optional[CtpReadOnlySession] = open_read_only(request)
    except CtpSandboxReadOnlyAdmissionError:
        raise
    except Exception:
        _reject("session_factory_failed", "unable to open CTP read-only session")
    if session is None:
        _reject("invalid_session", "CTP read-only session factory returned no session")

    result: Optional[CtpSandboxReadOnlyObservation] = None
    error: Optional[CtpSandboxReadOnlyAdmissionError] = None
    close_read_only = None
    try:
        try:
            close_read_only = getattr(session, "close_read_only", None)
            if not callable(close_read_only):
                _reject("invalid_session", "CTP read-only session has no close operation")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            read_identity = getattr(session, "read_identity", None)
            read_snapshot = getattr(session, "read_query_snapshot", None)
            if not callable(read_identity) or not callable(read_snapshot):
                _reject("invalid_session", "CTP read-only session has an invalid protocol")

            first_identity = _normalise_identity(read_identity(), "session identity")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if not _matching_identity(request, first_identity):
                if first_identity.provider != CTP_PROVIDER:
                    _reject(
                        "session_provider_mismatch",
                        "CTP session provider does not match registration",
                    )
                if first_identity.environment != admission.environment:
                    _reject(
                        "session_environment_mismatch",
                        "CTP session environment does not match registration",
                    )
                _reject(
                    "session_account_mismatch", "CTP session account does not match registration"
                )

            snapshot = _normalise_snapshot(read_snapshot())
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if snapshot.identity != first_identity:
                _reject(
                    "snapshot_identity_mismatch",
                    "CTP query snapshot identity does not match session",
                )

            final_identity = _normalise_identity(read_identity(), "final session identity")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if final_identity != first_identity:
                _reject(
                    "session_identity_changed", "CTP session identity changed during observation"
                )

            native_certificate_sha256 = _snapshot_native_certificate_sha256(snapshot)
            result = CtpSandboxReadOnlyObservation(
                runtime_id=effective.registration.runtime_id or "",
                strategy_id=effective.strategy_id,
                effective_config_digest=effective.effective_digest,
                registration_digest=effective.registration.digest,
                provider=first_identity.provider,
                environment=first_identity.environment,
                sdk_profile=admission.sdk_profile,
                account_fingerprint_sha256=first_identity.account_fingerprint_sha256,
                instrument_id=admission.instrument_id,
                exchange_id=admission.exchange_id,
                hedge_flag=admission.hedge_flag,
                trading_day=first_identity.trading_day,
                connection_generation=first_identity.connection_generation,
                query_snapshot=snapshot,
                native_certificate_sha256=native_certificate_sha256,
                native_certificate_provenance=(
                    "UNVERIFIED_DIGEST_ONLY"
                    if native_certificate_sha256 is not None
                    else "LOCAL_ONLY"
                ),
            )
        except CtpSandboxReadOnlyAdmissionError as caught:
            error = caught
        except Exception:
            error = CtpSandboxReadOnlyAdmissionError(
                "read_only_session_failed", "CTP sandbox read-only session failed"
            )
    finally:
        if callable(close_read_only):
            try:
                close_read_only()
            except Exception:
                if error is None:
                    error = CtpSandboxReadOnlyAdmissionError(
                        "session_close_failed", "unable to close CTP read-only session"
                    )
    if error is None:
        try:
            _require_session_deadline(request.valid_until, monotonic_deadline)
        except CtpSandboxReadOnlyAdmissionError as caught:
            error = caught
    if error is not None:
        raise error
    if result is None:
        _reject("read_only_session_failed", "CTP sandbox read-only session failed")
    return result


__all__ = [
    "CtpSandboxReadOnlyAdmissionError",
    "CtpSandboxReadOnlyObservation",
    "CtpSandboxReadOnlyRegistration",
    "admit_ctp_simnow_sandbox_readonly",
    "require_ctp_sandbox_readonly_runtime_contract",
]
