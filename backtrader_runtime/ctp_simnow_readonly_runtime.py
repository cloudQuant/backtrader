"""One sealed, CTP SimNow private-account read-only composition entry point.

This is deliberately a narrow composition root, not a registered runtime,
CLI command, provider admission, or execution route.  It joins four already
separate contracts in a fixed order:

1. validate the exact sealed Iteration 41 ``simulation/sandbox`` admission;
2. validate the exact sealed CTP credential scope before any secret I/O;
3. validate the installed CTP SDK import origin before any secret I/O;
4. resolve and re-seal one credential payload; and
5. run the seven-query TD read-only observation and close that client;
6. only then load the pinned installation's MdClient and verify one market
   login, one exact single-instrument subscription, and a bounded matching
   tick observation; and
7. return both non-authoritative observations.

There is no order, cancellation, settlement, arm, or external-write API here.
A successful observation proves only that this process completed one bounded
seven-query TD account session and one exact-contract MD login/subscription/
tick check through the installed SDK import boundary. It is not independent native
market-data QA, provider account acceptance, an approval receipt, a trading
permit, or a production route.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .capability_imports import trusted_installed_capability_import_context
from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    verify_ctp_sdk_artifact_provenance_for_fronts,
)
from .credential_resolver import (
    CTP_AUTHENTICATION_CREDENTIAL_KEYS,
    CredentialResolutionError,
    RuntimeCredentialScope,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from .ctp_sandbox_readonly_admission import (
    CtpSandboxReadOnlyAdmissionError,
    CtpSandboxReadOnlyObservation,
    CtpSandboxReadOnlyRegistration,
    admit_ctp_simnow_sandbox_readonly,
    require_ctp_sandbox_readonly_runtime_contract,
)
from .ctp_sdk_readonly import (
    CtpSdkReadOnlyError,
    CtpSdkReadOnlyScope,
    CtpSdkReadOnlySessionFactory,
    _default_sdk_components as _ctp_sdk_default_components,
)
from .ctp_sdk_market_readonly import (
    CtpSdkMarketReadOnlyError,
    CtpSdkMarketReadOnlyObservation,
    _probe_ctp_market_readonly,
)
from .errors import RuntimeConfigError
from .registry import EffectiveRuntimeConfig, RuntimeRegistry


_MD_TICK_OBSERVATION_SECONDS = 5.0
_MAX_CONFIGURED_FRONT_PAIRS = 8


class CtpSimNowReadOnlyRuntimeError(ValueError):
    """Redacted composition failure with no credentials or opaque refs."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpSimNowReadOnlyRuntimeError(reason, message)


def _normalise_credential_scope(value: Any) -> RuntimeCredentialScope:
    """Snapshot exact scope data without accepting subclasses or dynamic fields."""

    if type(value) is not RuntimeCredentialScope:
        _reject(
            "credential_scope_required",
            "a code-owned CTP credential scope is required for the read-only route",
        )
    try:
        return RuntimeCredentialScope(
            runtime_id=value.runtime_id,
            strategy_id=value.strategy_id,
            provider=value.provider,
            provider_environment=value.provider_environment,
            policy_environment=value.policy_environment,
            mode=value.mode,
            preset=value.preset,
            account_access=value.account_access,
            account_fingerprint_sha256=value.account_fingerprint_sha256,
            secrets_ref=value.secrets_ref,
            credential_keys=value.credential_keys,
            effective_config_digest=value.effective_config_digest,
            registration_digest=value.registration_digest,
        )
    except Exception:
        _reject(
            "credential_scope_invalid", "the CTP credential scope is not a valid code-owned binding"
        )
    raise AssertionError("unreachable")


def _require_matching_ctp_scope(
    admission: CtpSandboxReadOnlyRegistration,
    effective: EffectiveRuntimeConfig,
    scope: RuntimeCredentialScope,
) -> RuntimeCredentialScope:
    """Reject a scope that could select another CTP account or environment.

    This gate deliberately occurs before ``resolve_runtime_credentials`` so a
    bad admission or code-owned scope cannot trigger Credential Manager/file
    access.  The resolver repeats the sealed effective-config binding before
    it reads the selected secret source.
    """

    snapshot = _normalise_credential_scope(scope)
    from .config import CtpSimNowPrivateConfig

    private = effective.config.ctp_simnow
    if type(private) is not CtpSimNowPrivateConfig:
        _reject(
            "credential_scope_mismatch",
            "the CTP credential scope does not match the sealed sandbox admission",
        )
    try:
        configured_pairs = tuple(
            (pair["md_front"], pair["td_front"]) for pair in private.front_pairs
        )
    except Exception:
        _reject(
            "credential_scope_mismatch",
            "the CTP credential scope does not match the sealed sandbox admission",
        )
    selected_pair = (admission.md_front, admission.td_front)
    if (
        selected_pair not in configured_pairs
        or admission.environment != "simnow"
        or admission.sdk_profile != "config_front_pair"
        or snapshot.provider != "ctp"
        or snapshot.provider_environment != "simnow"
        or snapshot.policy_environment != "sandbox"
        or snapshot.mode != "simulation"
        or snapshot.preset != "sandbox"
        or snapshot.account_access != "sandbox_private_read"
        or snapshot.secrets_ref != admission.allowed_secrets_ref
        or snapshot.credential_keys != CTP_AUTHENTICATION_CREDENTIAL_KEYS
        or snapshot.runtime_id != effective.registration.runtime_id
        or snapshot.strategy_id != effective.strategy_id
        or snapshot.effective_config_digest != effective.effective_digest
        or snapshot.registration_digest != effective.registration.digest
        or not hmac.compare_digest(
            snapshot.account_fingerprint_sha256,
            admission.account_fingerprint_sha256,
        )
    ):
        _reject(
            "credential_scope_mismatch",
            "the CTP credential scope does not match the sealed sandbox admission",
        )
    return snapshot


def _sdk_scope_from_admission(admission: CtpSandboxReadOnlyRegistration) -> CtpSdkReadOnlyScope:
    """Make the SDK query scope solely from the exact sealed admission object."""

    try:
        return CtpSdkReadOnlyScope(
            environment=admission.environment,
            sdk_profile=admission.sdk_profile,
            account_fingerprint_sha256=admission.account_fingerprint_sha256,
            instrument_id=admission.instrument_id,
            exchange_id=admission.exchange_id,
            hedge_flag=admission.hedge_flag,
            td_front=admission.td_front,
            md_front=admission.md_front,
        )
    except Exception:
        _reject(
            "sdk_scope_invalid",
            "the code-owned CTP sandbox admission has no exact SDK read-only scope",
        )
    raise AssertionError("unreachable")


def _default_sdk_components() -> Tuple[Any, ...]:
    """Use the adapter's fixed loader; this private name is a unit-test seam.

    The public composition API deliberately accepts no caller-provided SDK
    loader.  Keeping the seam private prevents an operator from producing a
    native-looking observation with a substituted client or endpoint.
    """

    return _ctp_sdk_default_components()


class _SealedCtpCredentialSource:
    """Revalidate resolver provenance immediately before each SDK credential read.

    The SDK factory receives this narrow protocol object rather than the raw
    resolver result.  A seal checked only once at factory construction could
    become stale before a later ``require_credential`` call, so each access
    repeats the exact effective-config, registry, and scope binding.
    """

    __slots__ = ("_credentials", "_effective", "_registry", "_scope")

    def __init__(
        self,
        credentials: Any,
        effective: EffectiveRuntimeConfig,
        registry: RuntimeRegistry,
        scope: RuntimeCredentialScope,
    ) -> None:
        self._credentials = credentials
        self._effective = effective
        self._registry = registry
        self._scope = scope

    def __repr__(self) -> str:
        return "_SealedCtpCredentialSource(credentials=<redacted>)"

    def require_credential(self, name: str) -> str:
        if type(name) is not str or name not in CTP_AUTHENTICATION_CREDENTIAL_KEYS:
            raise CredentialResolutionError(
                "credential_name_not_available", "the requested CTP credential is not available"
            )
        require_resolved_runtime_credentials_seal(
            self._credentials,
            self._effective,
            self._registry,
            self._scope,
        )
        return self._credentials.require_credential(name)


@dataclass(frozen=True)
class CtpSimNowFrontSelectionAudit:
    """Opt-in, endpoint-free identity for one selected sealed config pair."""

    selected_config_index: int
    candidate_count: int
    selected_front_pair_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.selected_config_index) is not int
            or type(self.candidate_count) is not int
            or not 1 <= self.candidate_count <= _MAX_CONFIGURED_FRONT_PAIRS
            or not 0 <= self.selected_config_index < self.candidate_count
            or self.selected_config_index > 7
            or type(self.selected_front_pair_sha256) is not str
            or len(self.selected_front_pair_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.selected_front_pair_sha256
            )
        ):
            raise ValueError("invalid CTP SimNow front selection audit")

    def as_public_dict(self) -> Dict[str, Any]:
        """Return pair comparability without exposing configured endpoints."""

        return {
            "schema_version": 1,
            "selected_config_index": self.selected_config_index,
            "candidate_count": self.candidate_count,
            "selected_front_pair_sha256": self.selected_front_pair_sha256,
        }


@dataclass(frozen=True)
class CtpSimNowReadOnlyRuntimeObservation:
    """A redacted read-only result that intentionally grants no authority."""

    observation: CtpSandboxReadOnlyObservation
    market_data_observation: CtpSdkMarketReadOnlyObservation
    market_data_trading_writes: int = 0
    credentials_resolved: bool = True
    provider_connected: bool = False
    account_identity_verified: bool = False
    preflight_authorized: bool = False
    execution_authorized: bool = False
    external_writes_authorized: bool = False
    order_submission_authorized: bool = False
    cancellation_authorized: bool = False
    settlement_authorized: bool = False
    arming_authorized: bool = False
    external_write_requests: int = 0
    front_selection_audit: Optional[CtpSimNowFrontSelectionAudit] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.observation) is not CtpSandboxReadOnlyObservation:
            raise TypeError("observation must be a CtpSandboxReadOnlyObservation")
        if type(self.market_data_observation) is not CtpSdkMarketReadOnlyObservation:
            raise TypeError("market_data_observation must be a CtpSdkMarketReadOnlyObservation")
        if (
            self.front_selection_audit is not None
            and type(self.front_selection_audit) is not CtpSimNowFrontSelectionAudit
        ):
            raise TypeError("front_selection_audit must be a CtpSimNowFrontSelectionAudit")
        if (
            self.credentials_resolved is not True
            or self.provider_connected is not False
            or self.account_identity_verified is not False
            or self.preflight_authorized is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
            or self.order_submission_authorized is not False
            or self.cancellation_authorized is not False
            or self.settlement_authorized is not False
            or self.arming_authorized is not False
            or type(self.external_write_requests) is not int
            or self.external_write_requests != 0
            or type(self.market_data_trading_writes) is not int
            or self.market_data_trading_writes != 0
        ):
            raise ValueError("the CTP SimNow read-only result cannot grant authority")
        if (
            self.observation.execution_authorized is not False
            or self.observation.external_writes_authorized is not False
            or self.observation.order_submission_authorized is not False
            or self.observation.cancellation_authorized is not False
            or self.observation.settlement_authorized is not False
            or self.observation.arming_authorized is not False
            or self.observation.external_write_requests != 0
        ):
            raise ValueError("the nested CTP observation must remain zero-write")
        if (
            self.market_data_observation.market_login_ready is not True
            or self.market_data_observation.subscription_acknowledged is not True
            or self.market_data_observation.tick_observation_count < 1
            or self.market_data_observation.probe_session_closed is not True
            or self.market_data_observation.account_fingerprint_sha256
            != self.observation.account_fingerprint_sha256
            or self.market_data_observation.instrument_id != self.observation.instrument_id
            or self.market_data_observation.exchange_id != self.observation.exchange_id
            or self.market_data_observation.order_submission_authorized is not False
            or self.market_data_observation.trading_writes != 0
            or self.market_data_observation.settlement_writes != 0
        ):
            raise ValueError(
                "the market-data probe must be bound, observed, closed, and zero-write"
            )
        tick_binding = self.market_data_observation.tick_binding
        if (
            tick_binding is None
            or tick_binding.account_fingerprint_sha256
            != self.market_data_observation.account_fingerprint_sha256
            or tick_binding.md_front_sha256 != self.market_data_observation.md_front_sha256
            or tick_binding.instrument_id != self.market_data_observation.instrument_id
            or tick_binding.exchange_id != self.market_data_observation.exchange_id
            or tick_binding.connection_generation
            != self.market_data_observation.connection_generation
        ):
            raise ValueError("the market-data tick binding must match the closed MD observation")

    def __bool__(self) -> bool:
        raise TypeError(
            "CtpSimNowReadOnlyRuntimeObservation is not account, preflight, or execution authority; "
            "do not use it as a boolean"
        )

    def as_public_dict(self) -> Dict[str, Any]:
        """Return only read-only facts and non-authority state."""

        return {
            "credentials_resolved": self.credentials_resolved,
            "provider_connected": self.provider_connected,
            "account_identity_verified": self.account_identity_verified,
            "preflight_authorized": self.preflight_authorized,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "settlement_authorized": self.settlement_authorized,
            "arming_authorized": self.arming_authorized,
            "external_write_requests": self.external_write_requests,
            "market_data_trading_writes": self.market_data_trading_writes,
            "read_only_observation": self.observation.as_public_dict(),
            "market_data_observation": self.market_data_observation.as_public_dict(),
        }

    def as_front_selection_audit_dict(self) -> Dict[str, Any]:
        """Return opt-in configured-pair identity, separate from frozen I2 evidence."""

        if self.front_selection_audit is None:
            raise ValueError("this observation has no selected config index audit")
        return self.front_selection_audit.as_public_dict()


def _front_selection_audit(
    effective: EffectiveRuntimeConfig,
    admission: CtpSandboxReadOnlyRegistration,
    selected_config_index: Any,
) -> Optional[CtpSimNowFrontSelectionAudit]:
    """Validate an optional config index before any credential or SDK access."""

    if selected_config_index is None:
        return None
    from .config import CtpSimNowPrivateConfig

    private = effective.config.ctp_simnow
    front_pairs = getattr(private, "front_pairs", None)
    if (
        type(private) is not CtpSimNowPrivateConfig
        or type(front_pairs) is not tuple
        or not 1 <= len(front_pairs) <= _MAX_CONFIGURED_FRONT_PAIRS
        or type(selected_config_index) is not int
        or selected_config_index < 0
        or selected_config_index >= len(front_pairs)
        or selected_config_index > 7
    ):
        _reject(
            "configured_front_selection_invalid",
            "the selected CTP config index is outside the sealed candidate set",
        )
    try:
        selected_pair = front_pairs[selected_config_index]
        md_front = selected_pair["md_front"]
        td_front = selected_pair["td_front"]
    except Exception:
        _reject(
            "configured_front_selection_invalid",
            "the selected CTP config index does not identify one sealed front pair",
        )
    if (admission.md_front, admission.td_front) != (md_front, td_front):
        _reject(
            "configured_front_selection_mismatch",
            "the admitted CTP front pair does not match the selected sealed config index",
        )
    md_bytes = md_front.encode("utf-8")
    td_bytes = td_front.encode("utf-8")
    pair_digest = hashlib.sha256(
        b"backtrader.ctp.simnow.front-pair-audit.v1\0"
        + len(md_bytes).to_bytes(4, "big")
        + md_bytes
        + len(td_bytes).to_bytes(4, "big")
        + td_bytes
    ).hexdigest()
    try:
        return CtpSimNowFrontSelectionAudit(
            selected_config_index=selected_config_index,
            candidate_count=len(front_pairs),
            selected_front_pair_sha256=pair_digest,
        )
    except Exception:
        _reject(
            "configured_front_selection_invalid",
            "the selected CTP config index could not be represented as a safe audit",
        )
    raise AssertionError("unreachable")


def _load_installed_md_client_type() -> Any:
    """Load MdClient lazily inside the already validated capability fence."""

    from bt_api_ctp.ctp.client import MdClient

    return MdClient


def open_ctp_simnow_readonly_runtime(
    *,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpSandboxReadOnlyRegistration,
    credential_scope: RuntimeCredentialScope,
    connect_timeout: float = 15.0,
    query_timeout: float = 5.0,
    selected_config_index: Optional[int] = None,
) -> CtpSimNowReadOnlyRuntimeObservation:
    """Run one bounded CTP SimNow private query with no execution interface.

    The strict admission and credential-scope gates happen before secret I/O.
    An installed-root capability-origin gate then runs before credential
    resolution. The resolver's result is re-sealed before the SDK factory
    exists, so a caller cannot substitute a manually constructed credential
    object. The seven-query TraderClient pass and a separate single-contract
    MdClient pass must both succeed, including a matching post-ACK tick. The MD client is imported only after the
    TD observation completes, while still inside the same artifact-verified
    installed-capability context. This preflight should run in an isolated
    process with no other same-account market-data client active; its probe
    lease coordinates only cooperating probe invocations. The returned object
    contains no credential source, secret values, client, session handle, or
    caller-controlled SDK loader.
    """

    try:
        admission = require_ctp_sandbox_readonly_runtime_contract(
            effective,
            registry,
            admission_registration,
        )
    except CtpSandboxReadOnlyAdmissionError:
        _reject(
            "runtime_admission_rejected",
            "the sealed CTP SimNow sandbox admission was rejected before credential access",
        )
    except Exception:
        _reject(
            "runtime_admission_rejected",
            "the sealed CTP SimNow sandbox admission was rejected before credential access",
        )

    scope = _require_matching_ctp_scope(admission, effective, credential_scope)
    front_selection_audit = _front_selection_audit(effective, admission, selected_config_index)
    sdk_scope = _sdk_scope_from_admission(admission)

    # Resolve the exact installed package before Credential Manager/file I/O.
    # This strict context rejects CWD, source-root, absolute ``PYTHONPATH``,
    # cached, and editable-meta-path substitutions.  It is an origin fence,
    # not a wheel signature, release-provenance, dependency-lock, or arbitrary
    # trusted-in-process-code verifier.  The private test loader seam need not
    # import a capability, but it remains inside this fixed one-name boundary.
    try:
        # The CTP package's public initializer imports container types from
        # bt_api_base, so both installed distributions are part of this fixed
        # read-only capability boundary.
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            # Artifact, RECORD, and canonical selected-front checks run before
            # any Credential Manager or file-backed secret access. The import
            # context has already excluded source/editable/CWD package origins.
            try:
                verify_ctp_sdk_artifact_provenance_for_fronts(
                    td_front=admission.td_front,
                    md_front=admission.md_front,
                )
            except CtpArtifactProvenanceError:
                _reject(
                    "capability_provenance_rejected",
                    "the installed CTP SDK artifact or selected front pair was rejected before credential access",
                )

            try:
                credentials = resolve_runtime_credentials(effective, registry, scope)
                require_resolved_runtime_credentials_seal(credentials, effective, registry, scope)
            except CredentialResolutionError:
                _reject(
                    "credential_resolution_rejected",
                    "the CTP credential source was rejected before native session setup",
                )
            except Exception:
                _reject(
                    "credential_resolution_rejected",
                    "the CTP credential source was rejected before native session setup",
                )

            credential_source = _SealedCtpCredentialSource(credentials, effective, registry, scope)
            try:
                factory = CtpSdkReadOnlySessionFactory(
                    sdk_scope,
                    credential_source,
                    connect_timeout=connect_timeout,
                    query_timeout=query_timeout,
                    sdk_components_loader=_default_sdk_components,
                )
                observation = admit_ctp_simnow_sandbox_readonly(
                    effective=effective,
                    registry=registry,
                    admission_registration=admission,
                    session_factory=factory,
                )
            except CtpSandboxReadOnlyAdmissionError:
                _reject(
                    "read_only_observation_rejected", "the CTP read-only observation was rejected"
                )
            except CtpSdkReadOnlyError:
                _reject(
                    "native_readonly_session_rejected",
                    "the native CTP read-only session was rejected",
                )
            except Exception:
                _reject(
                    "native_readonly_session_rejected",
                    "the native CTP read-only session was rejected",
                )
            # Do not load or construct MdClient until the registry/config,
            # artifact and credential gates have passed and all seven TD
            # queries have completed with the TraderClient closed.
            try:
                md_client_type = _load_installed_md_client_type()
                market_observation = _probe_ctp_market_readonly(
                    admission=admission,
                    credential_source=credential_source,
                    client_type=md_client_type,
                    timeout_seconds=connect_timeout,
                    tick_observation_seconds=min(_MD_TICK_OBSERVATION_SECONDS, connect_timeout),
                )
            except CtpSdkMarketReadOnlyError as exc:
                _reject(
                    exc.reason,
                    "the exact CTP market-data login or single-instrument subscription was rejected",
                )
            except CtpSimNowReadOnlyRuntimeError:
                raise
            except Exception:
                _reject(
                    "market_readonly_observation_rejected",
                    "the exact CTP market-data login or single-instrument subscription was rejected",
                )
            if (
                market_observation.md_front_sha256
                != hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
                or market_observation.account_fingerprint_sha256
                != admission.account_fingerprint_sha256
                or market_observation.instrument_id != admission.instrument_id
                or market_observation.exchange_id != admission.exchange_id
                or market_observation.market_login_ready is not True
                or market_observation.subscription_acknowledged is not True
            ):
                _reject(
                    "market_observation_mismatch",
                    "the CTP market-data observation did not match the sealed route",
                )
            if market_observation.tick_observation_count < 1:
                _reject(
                    "market_tick_not_observed",
                    "the exact CTP market-data scope produced no matching tick in the bounded window",
                )
            tick_binding = market_observation.tick_binding
            if (
                tick_binding is None
                or tick_binding.account_fingerprint_sha256 != admission.account_fingerprint_sha256
                or tick_binding.md_front_sha256
                != hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
                or tick_binding.instrument_id != admission.instrument_id
                or tick_binding.exchange_id != admission.exchange_id
                or tick_binding.connection_generation != market_observation.connection_generation
            ):
                _reject(
                    "market_tick_binding_mismatch",
                    "the observed CTP tick did not match the sealed market-data scope",
                )
            if market_observation.probe_session_closed is not True:
                _reject(
                    "market_client_close_incomplete",
                    "the CTP market-data client did not prove completed shutdown",
                )
    except CtpSimNowReadOnlyRuntimeError:
        raise
    except RuntimeConfigError:
        _reject(
            "capability_origin_rejected",
            "the installed CTP capability import origin was rejected before credential access",
        )
    except Exception:
        _reject(
            "capability_origin_rejected",
            "the installed CTP capability import origin was rejected before credential access",
        )
    return CtpSimNowReadOnlyRuntimeObservation(
        observation=observation,
        market_data_observation=market_observation,
        front_selection_audit=front_selection_audit,
    )


__all__ = [
    "CtpSimNowFrontSelectionAudit",
    "CtpSimNowReadOnlyRuntimeError",
    "CtpSimNowReadOnlyRuntimeObservation",
    "open_ctp_simnow_readonly_runtime",
]
