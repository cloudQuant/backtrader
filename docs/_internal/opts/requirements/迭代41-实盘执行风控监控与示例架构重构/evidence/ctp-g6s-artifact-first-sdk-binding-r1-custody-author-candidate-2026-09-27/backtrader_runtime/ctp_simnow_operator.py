"""Operator dispatch for a code-registered CTP SimNow read-only route.

The public CLI accepts only a registered runtime directory.  The legacy
static binding remains constructible for compatibility checks, but dispatch
rejects it. A code-owned policy binding consumes the TD/MD front pair selected
from one sealed private config block without an endpoint allowlist or
set/profile selection. It passes both strings unchanged into the private-read
admission. No calendar, clock, or environment variable selects an endpoint;
the TCP probe selects only among configured candidates and authorizes nothing.
No binding grants execution authority.

The default inventory has one config-driven binding for the reserved private
runtime. It grants no runner or execution authority. Preflight probes only the
ordered exact pairs in sealed config and binds one selected pair unchanged. A
passing transport probe does not release credentials: artifact provenance,
scoped credentials, account-bound TD queries, MD login/subscription/tick
callbacks, and zero-write checks remain separate gates. Constructing a binding
does not itself contact SimNow or grant account/execution authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_REF_RE = re.compile(
    r"^(?:runtime_secrets|os_secret_store:[A-Za-z0-9][A-Za-z0-9._-]{0,127})$"
)
_SIMNOW_ENVIRONMENT_RE = re.compile(r"^simnow_set[12]$")
_OFFICIAL_SIMNOW_PROFILES = frozenset({"set1_group1", "set1_group2", "set2_7x24"})
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_CTP_EXCHANGES = frozenset({"CZCE", "DCE", "SHFE", "INE", "CFFEX", "GFEX"})
_CONFIG_YAML_REF = "config_yaml"
_FRONT_PROBE_TIMEOUT_SECONDS = 3.0
_FRONT_PROBE_MAX_PAIRS = 8
_FRONT_PROBE_REPEATED_SAMPLES = 3


def _invalid_binding() -> ValueError:
    return ValueError("invalid code-owned CTP SimNow read-only binding")


@dataclass(frozen=True)
class CtpSimNowReadOnlyBinding:
    """Legacy static metadata retained for validation compatibility only.

    This is not an approval receipt.  It carries no credential values, SDK
    loader, provider object, order/cancel capability, or production setting.
    The operator dispatcher never uses it to open a private-read route.
    ``account_fingerprint_sha256`` is private in repr and is never included in
    operator errors.
    """

    runtime_id: str
    environment: str
    sdk_profile: str
    account_fingerprint_sha256: str = field(repr=False)
    secrets_ref: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    session_ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        if (
            type(self.runtime_id) is not str
            or not self.runtime_id.strip()
            or not _IDENTIFIER_RE.fullmatch(self.runtime_id)
        ):
            raise _invalid_binding()
        if type(self.environment) is not str or not _SIMNOW_ENVIRONMENT_RE.fullmatch(
            self.environment
        ):
            raise _invalid_binding()
        if (
            type(self.sdk_profile) is not str
            or self.sdk_profile not in _OFFICIAL_SIMNOW_PROFILES
            or self.sdk_profile[3] != self.environment[-1]
        ):
            raise _invalid_binding()
        if type(self.account_fingerprint_sha256) is not str or not _SHA256_RE.fullmatch(
            self.account_fingerprint_sha256
        ):
            raise _invalid_binding()
        if (
            type(self.secrets_ref) is not str
            or not _SECRET_REF_RE.fullmatch(self.secrets_ref)
            or self.secrets_ref == "none"
        ):
            raise _invalid_binding()
        if type(self.instrument_id) is not str or not _INSTRUMENT_RE.fullmatch(self.instrument_id):
            raise _invalid_binding()
        if type(self.exchange_id) is not str or not _EXCHANGE_RE.fullmatch(self.exchange_id):
            raise _invalid_binding()
        if type(self.hedge_flag) is not str or self.hedge_flag not in ("1", "2", "3"):
            raise _invalid_binding()
        if type(self.session_ttl_seconds) not in (int, float):
            raise _invalid_binding()
        try:
            ttl = float(self.session_ttl_seconds)
        except (OverflowError, TypeError, ValueError):
            raise _invalid_binding() from None
        if not math.isfinite(ttl) or not 0.0 < ttl <= 300.0:
            raise _invalid_binding()
        object.__setattr__(self, "session_ttl_seconds", ttl)

    def _admission(self, registration: RegisteredRuntime) -> Any:
        """Create the fixed admission only after registry identity is checked."""

        from .ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
        from .ctp_artifact_provenance import simnow_fronts_for_profile

        td_front, md_front = simnow_fronts_for_profile(self.sdk_profile)

        return CtpSandboxReadOnlyRegistration(
            runtime_registration=registration,
            environment=self.environment,
            sdk_profile=self.sdk_profile,
            account_fingerprint_sha256=self.account_fingerprint_sha256,
            allowed_secrets_ref=self.secrets_ref,
            instrument_id=self.instrument_id,
            exchange_id=self.exchange_id,
            hedge_flag=self.hedge_flag,
            td_front=td_front,
            md_front=md_front,
            session_ttl_seconds=self.session_ttl_seconds,
        )

    def _credential_scope(self, effective: EffectiveRuntimeConfig) -> Any:
        """Derive authentication scope from the sealed config and this binding."""

        from .credential_resolver import CTP_AUTHENTICATION_CREDENTIAL_KEYS, RuntimeCredentialScope

        return RuntimeCredentialScope(
            runtime_id=self.runtime_id,
            strategy_id=effective.strategy_id,
            provider="ctp",
            provider_environment=self.environment,
            policy_environment="sandbox",
            mode="simulation",
            preset="sandbox",
            account_access="sandbox_private_read",
            account_fingerprint_sha256=self.account_fingerprint_sha256,
            secrets_ref=self.secrets_ref,
            credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
            effective_config_digest=effective.effective_digest,
            registration_digest=effective.registration.digest,
        )


def _front_error() -> RuntimeConfigError:
    return _operator_error(
        "ctp_simnow_preflight_front_rejected",
        "the sealed SimNow config must provide a valid configured TD/MD front pair",
    )


def _select_configured_front_pair(front_pairs: tuple[Any, ...]) -> Any:
    """Probe only sealed configured pairs and redact endpoint-specific failures."""

    from .ctp_front_pair_probe import CtpFrontPairProbeError, select_ctp_front_pair

    try:
        return select_ctp_front_pair(
            front_pairs,
            timeout_seconds=_FRONT_PROBE_TIMEOUT_SECONDS,
            max_pairs=_FRONT_PROBE_MAX_PAIRS,
            repeated_samples=_FRONT_PROBE_REPEATED_SAMPLES,
        )
    except CtpFrontPairProbeError:
        raise _operator_error(
            "ctp_simnow_preflight_front_probe_rejected",
            "configured CTP front TCP probing failed; SDK, credential resolution, and account queries were not started",
        ) from None
    except Exception:
        # Keep the operator boundary redacted even if the selector itself is
        # unavailable or returns malformed internal state.
        raise _operator_error(
            "ctp_simnow_preflight_front_probe_rejected",
            "configured CTP front TCP probing failed; SDK, credential resolution, and account queries were not started",
        ) from None


def _resolve_selected_front_pair(front_pairs: tuple[Any, ...], *, selected_front_pair: Any) -> Any:
    """Require a selector result to be exactly one member of sealed config."""

    from .ctp_front_pair_probe import CtpConfiguredFrontPair

    if selected_front_pair is None:
        if len(front_pairs) != 1:
            raise _operator_error(
                "ctp_simnow_preflight_front_selection_required",
                "multiple configured CTP front pairs require an explicit probe selection",
            )
        candidate = front_pairs[0]
        md_front = candidate.get("md_front") if hasattr(candidate, "get") else None
        td_front = candidate.get("td_front") if hasattr(candidate, "get") else None
        selected_front_pair = CtpConfiguredFrontPair(md_front=md_front, td_front=td_front)
    if (
        type(selected_front_pair) is not CtpConfiguredFrontPair
        or type(selected_front_pair.md_front) is not str
        or type(selected_front_pair.td_front) is not str
    ):
        raise _operator_error(
            "ctp_simnow_preflight_front_selection_required",
            "the configured CTP front selector did not return one exact address pair",
        )
    if not any(
        hasattr(candidate, "get")
        and candidate.get("md_front") == selected_front_pair.md_front
        and candidate.get("td_front") == selected_front_pair.td_front
        for candidate in front_pairs
    ):
        raise _operator_error(
            "ctp_simnow_preflight_front_selection_mismatch",
            "the selected CTP front pair is not present in the sealed config",
        )
    return selected_front_pair


def _validate_selected_config_index(
    front_pairs: tuple[Any, ...], *, selected_front_pair: Any, selected_config_index: Any
) -> int | None:
    """Bind an optional selector index to the exact sealed config pair."""

    if selected_config_index is None:
        return None
    if (
        type(selected_config_index) is not int
        or selected_config_index < 0
        or selected_config_index >= len(front_pairs)
        or selected_config_index > 7
    ):
        raise _operator_error(
            "ctp_simnow_preflight_front_selection_mismatch",
            "the selected CTP config index is outside the sealed candidate set",
        )
    candidate = front_pairs[selected_config_index]
    if (
        not hasattr(candidate, "get")
        or candidate.get("md_front") != selected_front_pair.md_front
        or candidate.get("td_front") != selected_front_pair.td_front
    ):
        raise _operator_error(
            "ctp_simnow_preflight_front_selection_mismatch",
            "the selected CTP config index does not identify the admitted front pair",
        )
    return selected_config_index


@dataclass(frozen=True)
class CtpSimNowConfigReadOnlyBinding:
    """Code-owned policy for one sealed, config-driven CTP read-only route.

    Instrument, exchange, hedge flag, credentials, and both front strings come
    from the sealed private config. The front strings pass through unchanged;
    this binding does not consult a static endpoint allowlist or derive a
    profile from the address pair. This binding contains no account or
    credential value and has no time-based endpoint policy.
    """

    runtime_id: str
    session_ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        if type(self.runtime_id) is not str or not _IDENTIFIER_RE.fullmatch(self.runtime_id):
            raise _invalid_binding()
        if type(self.session_ttl_seconds) not in (int, float):
            raise _invalid_binding()
        try:
            ttl = float(self.session_ttl_seconds)
        except (OverflowError, TypeError, ValueError):
            raise _invalid_binding() from None
        if not math.isfinite(ttl) or not 0.0 < ttl <= 300.0:
            raise _invalid_binding()
        object.__setattr__(self, "session_ttl_seconds", ttl)

    @property
    def secrets_ref(self) -> str:
        return _CONFIG_YAML_REF

    def _route(
        self,
        effective: EffectiveRuntimeConfig,
        registry: RuntimeRegistry,
        *,
        selected_front_pair: Any = None,
        selected_config_index: Any = None,
    ) -> tuple[Any, Any]:
        from .credential_resolver import CTP_AUTHENTICATION_CREDENTIAL_KEYS, RuntimeCredentialScope
        from .ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration

        private, registration, front_pairs = self._sealed_private_config(effective, registry)
        # Scope is an explicit operator choice in the sealed config. Validate
        # the supported CTP shape here, but do not silently replace it with a
        # code-selected instrument or exchange.
        if (
            type(private.instrument_id) is not str
            or not _INSTRUMENT_RE.fullmatch(private.instrument_id)
            or type(private.exchange_id) is not str
            or private.exchange_id not in _CTP_EXCHANGES
            or type(private.hedge_flag) is not str
            or private.hedge_flag not in ("1", "2", "3")
        ):
            raise _operator_error(
                "ctp_simnow_preflight_query_scope_rejected",
                "the configured CTP instrument, exchange, or hedge scope is invalid",
            )
        selected_front_pair = _resolve_selected_front_pair(
            front_pairs, selected_front_pair=selected_front_pair
        )
        selected_config_index = _validate_selected_config_index(
            front_pairs,
            selected_front_pair=selected_front_pair,
            selected_config_index=selected_config_index,
        )
        try:
            td_front = selected_front_pair.td_front
            md_front = selected_front_pair.md_front
        except Exception:
            raise _operator_error(
                "ctp_simnow_preflight_front_selection_required",
                "the sealed config must resolve to one explicit CTP front pair",
            ) from None
        try:
            # These are policy labels, not selector inputs. The endpoints stay
            # exactly as sealed in config and no source/env field can replace
            # them or select a SimNow set.
            environment = "simnow"
            sdk_profile = "config_front_pair"
            account_fingerprint = hashlib.sha256(
                "{0}:{1}".format(private.broker_id, private.user_id).encode("utf-8")
            ).hexdigest()
            admission = CtpSandboxReadOnlyRegistration(
                runtime_registration=registration,
                environment=environment,
                sdk_profile=sdk_profile,
                account_fingerprint_sha256=account_fingerprint,
                allowed_secrets_ref=_CONFIG_YAML_REF,
                instrument_id=private.instrument_id,
                exchange_id=private.exchange_id,
                hedge_flag=private.hedge_flag,
                td_front=td_front,
                md_front=md_front,
                session_ttl_seconds=self.session_ttl_seconds,
            )
            scope = RuntimeCredentialScope(
                runtime_id=self.runtime_id,
                strategy_id=effective.strategy_id,
                provider="ctp",
                provider_environment=environment,
                policy_environment="sandbox",
                mode="simulation",
                preset="sandbox",
                account_access="sandbox_private_read",
                account_fingerprint_sha256=account_fingerprint,
                secrets_ref=_CONFIG_YAML_REF,
                credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
                effective_config_digest=effective.effective_digest,
                registration_digest=registration.digest,
            )
        except RuntimeConfigError:
            raise
        except Exception:
            raise _front_error() from None
        return admission, scope

    def _sealed_private_config(
        self, effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
    ) -> tuple[Any, RegisteredRuntime, tuple[Any, ...]]:
        """Validate the sealed route before any credential-free network probe."""

        from .config import CtpSimNowPrivateConfig

        require_effective_runtime_config_seal(effective, registry)
        registration = effective.registration
        private = effective.config.ctp_simnow
        front_pairs = getattr(private, "front_pairs", None)
        if (
            type(private) is not CtpSimNowPrivateConfig
            or effective.mode != "simulation"
            or effective.preset != "sandbox"
            or effective.config.secrets_ref != _CONFIG_YAML_REF
            or registration.runtime_id != self.runtime_id
            or type(front_pairs) is not tuple
            or not front_pairs
            or len(front_pairs) > _FRONT_PROBE_MAX_PAIRS
        ):
            raise _operator_error(
                "ctp_simnow_preflight_private_config_required",
                "the registered CTP route requires its sealed private config.yaml block",
            )
        # Validate non-endpoint scope before spending the bounded probe budget.
        if (
            type(private.instrument_id) is not str
            or not _INSTRUMENT_RE.fullmatch(private.instrument_id)
            or type(private.exchange_id) is not str
            or private.exchange_id not in _CTP_EXCHANGES
            or type(private.hedge_flag) is not str
            or private.hedge_flag not in ("1", "2", "3")
        ):
            raise _operator_error(
                "ctp_simnow_preflight_query_scope_rejected",
                "the configured CTP instrument, exchange, or hedge scope is invalid",
            )
        return private, registration, front_pairs


def _operator_error(reason: str, message: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        message,
        field_path="runtime.preset",
        reason=reason,
    )


def dispatch_registered_ctp_simnow_readonly_preflight(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> Any:
    """Run one registered read-only account preflight through the composition root.

    This function accepts no scope or SDK injection.  It resolves the route
    binding from the same trusted registry that sealed ``config.yaml`` and
    calls the real read-only composition API. The default registry resolves
    the config-driven binding; missing config fails at config loading, and the
    scoped SDK provenance gate runs before credential resolution or connection.
    """

    if type(effective) is not EffectiveRuntimeConfig or type(registry) is not RuntimeRegistry:
        raise _operator_error(
            "ctp_simnow_preflight_binding_required",
            "a sealed runtime configuration and trusted registry are required",
        )
    require_effective_runtime_config_seal(effective, registry)
    if effective.profile is not None or effective.registration.profiles:
        from .ctp_sandbox_readonly_admission import (
            CtpSandboxReadOnlyAdmissionError,
            require_ctp_sandbox_profile_runtime,
        )

        try:
            require_ctp_sandbox_profile_runtime(effective, registry)
        except CtpSandboxReadOnlyAdmissionError:
            raise _operator_error(
                "ctp_simnow_preflight_profile_dispatch_unavailable",
                "the profiled CTP route is not the exact zero-write sandbox binding",
            ) from None
    try:
        registration = registry.require_runtime_dir(effective.config.strategy_dir)
        if registration is not effective.registration:
            raise ValueError("registration mismatch")
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
    except RuntimeConfigError:
        raise
    except Exception:
        raise _operator_error(
            "ctp_simnow_preflight_route_unregistered",
            "no reviewed CTP SimNow read-only route is registered for this runtime",
        ) from None

    try:
        if type(binding) is CtpSimNowReadOnlyBinding:
            raise _operator_error(
                "ctp_simnow_preflight_front_policy_required",
                "CTP SimNow preflight requires sealed config.yaml front addresses",
            )
        if type(binding) is CtpSimNowConfigReadOnlyBinding:
            _, _, front_pairs = binding._sealed_private_config(effective, registry)
            selection = _select_configured_front_pair(front_pairs)
            selected_config_index = getattr(selection, "config_index", None)
            if selected_config_index is None:
                # Keep compatibility with older selector adapters that expose
                # the exact pair but not its candidate index. Config pairs are
                # unique, so deriving the index from that exact pair is safe.
                selected_config_index = next(
                    index
                    for index, candidate in enumerate(front_pairs)
                    if candidate.get("md_front") == selection.pair.md_front
                    and candidate.get("td_front") == selection.pair.td_front
                )
            admission, scope = binding._route(
                effective,
                registry,
                selected_front_pair=selection.pair,
                selected_config_index=selected_config_index,
            )
        else:
            raise _invalid_binding()
    except RuntimeConfigError:
        raise
    except Exception:
        raise _operator_error(
            "ctp_simnow_preflight_binding_invalid",
            "the registered CTP SimNow read-only route is invalid",
        ) from None

    # Import the provider-capable composition only after the sealed config and
    # exact code-owned route binding have both been resolved.
    from .ctp_simnow_readonly_runtime import (
        CtpSimNowReadOnlyRuntimeError,
        open_ctp_simnow_readonly_runtime,
    )

    try:
        return open_ctp_simnow_readonly_runtime(
            effective=effective,
            registry=registry,
            admission_registration=admission,
            credential_scope=scope,
            selected_config_index=selected_config_index,
        )
    except CtpSimNowReadOnlyRuntimeError as error:
        reason = "ctp_simnow_preflight_{0}".format(error.reason)
        raise _operator_error(
            reason,
            "the registered CTP SimNow read-only preflight was rejected",
        ) from None
    except RuntimeConfigError:
        raise
    except Exception:
        raise _operator_error(
            "ctp_simnow_preflight_rejected",
            "the registered CTP SimNow read-only preflight was rejected",
        ) from None


__all__ = [
    "CtpSimNowConfigReadOnlyBinding",
    "CtpSimNowReadOnlyBinding",
    "dispatch_registered_ctp_simnow_readonly_preflight",
]
