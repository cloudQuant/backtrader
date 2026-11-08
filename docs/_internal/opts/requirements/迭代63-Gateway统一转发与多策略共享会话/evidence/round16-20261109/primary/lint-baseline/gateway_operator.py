"""Trusted operator composition for the normal Gateway ServiceHost path.

This module is the product-side entry for composing one parsed service
configuration with trusted authority, local resources, the Gateway account
session owner, and the existing service-v2 Market Hub. It does not read
credentials or authority from the wire/config manifest. The operator supplies
those capabilities in-process, then calls ``start`` and repeatedly calls
``serve_once`` on the same thread (or uses ``serve_until_stopped``).

Only the configured Gateway role is assembled here. Other fixed service
components are resolved through the operator's existing ``resource_provider``.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional

from bt_api_base.service_protocol import WireScope

from .gateway_operator_market import GatewayMarketBinding
from .service_components import ComponentResources, ServiceResourceProvider
from .service_config import ServiceConfig
from .service_host import ServiceHost, TrustedServiceAuthority, TrustedServiceClients
from .service_runtime import ServiceClientRuntime

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class GatewayOperatorDeploymentError(RuntimeError):
    """Finite, value-free failure from trusted Gateway operator wiring."""

    _CODES = frozenset(
        {
            "INVALID_ACCOUNT_BINDING",
            "INVALID_DEPLOYMENT_CONFIG",
            "INVALID_MARKET_BINDING",
            "INVALID_RESOURCE_PROVIDER",
            "GATEWAY_COMPONENT_REQUIRED",
            "UNSUPPORTED_GATEWAY_ROLE",
            "ACCOUNT_SESSION_OWNER_REQUIRED",
            "ACCOUNT_PROVIDER_SESSION_PORT_REQUIRED",
            "ACCOUNT_SESSION_BINDING_REQUIRED",
            "ACCOUNT_SESSION_REFERENCE_MISMATCH",
            "ACCOUNT_PRINCIPAL_BINDING_INVALID",
            "ACCOUNT_SESSION_WORKER_UNAVAILABLE",
            "ACCOUNT_SESSION_RECOVERY_FAILED",
            "UNUSED_ACCOUNT_SESSION_BINDING",
            "MARKET_BINDING_REQUIRED",
            "MARKET_AUDIENCE_MISMATCH",
            "UNUSED_MARKET_BINDING",
            "OWNER_THREAD_REQUIRED",
            "ACCOUNT_PROVIDER_RESOLUTION_FAILED",
            "ACCOUNT_WORKER_BUILD_FAILED",
            "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED",
            "ACCOUNT_RESOURCE_WIRING_FAILED",
            "MARKET_HUB_BUILD_FAILED",
            "MARKET_PROVIDER_CLOSE_UNCONFIRMED",
            "MARKET_HISTORY_PROVIDER_CLOSE_UNCONFIRMED",
            "INVALID_STOP_EVENT",
            "INVALID_POLL_INTERVAL",
        }
    )

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in self._CODES:
            code = "GATEWAY_OPERATOR_DEPLOYMENT_FAILED"
        self.code = code
        super().__init__(code)


class _RetryableMarketCleanup:
    """Retain an owner-thread market cleanup callback until it succeeds."""

    __slots__ = ("_callback",)

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback

    def close(self) -> None:
        self._callback()


@dataclass(frozen=True, slots=True)
class GatewayAccountSessionBinding:
    """Trusted, local resources for one Gateway account-session worker.

    ``account_session_ref`` is matched against the parsed Gateway service
    options. The credential reference and resolver stay inside the separately
    injected ``GatewaySessionOwner``; neither is stored in this binding.
    """

    account_session_ref: str
    journal: object = field(repr=False)
    account_key: object = field(repr=False)
    account_scope: object = field(repr=False)
    state_scope: str
    guard: object = field(repr=False)
    required_coverage: tuple[object, ...]
    principals: Mapping[str, object] = field(repr=False)
    view_policies: tuple[object, ...] = field(default=(), repr=False)
    require_open_orders: bool = False
    refresh_interval_seconds: float = 1.0
    max_staleness_seconds: float = 5.0
    request_timeout_seconds: float = 2.0
    quota_admission: object | None = field(default=None, repr=False, compare=False)
    quota_domain_binding: object | None = field(default=None, repr=False, compare=False)
    _dispatch_quota_admission: Callable[
        [str, Optional[str], Optional[str], Optional[str], str, int], None
    ] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not _valid_ref(self.account_session_ref) or not _valid_ref(self.state_scope):
            raise GatewayOperatorDeploymentError("INVALID_ACCOUNT_BINDING")
        try:
            from bt_api_base.account_protocol import AccountKey, AccountResourceKey
            from bt_api_gateway.account_view_projection import (
                GatewayAccountViewPolicy,
                validate_policy_set,
            )
            from bt_api_gateway.event_journal import GatewayEventJournal
            from bt_api_gateway.quota_admission import (
                GatewayQuotaAdmission,
                GatewayQuotaDispatchAdmission,
                GatewayQuotaDomainBinding,
            )
            from bt_api_gateway.router import GatewayPrincipal
            from bt_api_gateway.service_component import GatewayServiceAccountScope
            from bt_api_gateway.session_guard import LocalAccountSessionGuard

            if self.quota_admission is not None and self.quota_domain_binding is not None:
                raise ValueError
            if (
                self.quota_domain_binding is not None
                and type(self.quota_domain_binding) is not GatewayQuotaDomainBinding
            ):
                raise ValueError
            effective_admission = (
                self.quota_domain_binding.admission
                if self.quota_domain_binding is not None
                else self.quota_admission
            )

            if (
                type(self.journal) is not GatewayEventJournal
                or type(self.account_key) is not AccountKey
                or type(self.account_scope) is not GatewayServiceAccountScope
                or type(self.guard) is not LocalAccountSessionGuard
                or self.guard.account_key_digest
                != hashlib.sha256(self.account_key.account_key_id.encode("ascii")).hexdigest()
                or (
                    effective_admission is not None
                    and type(effective_admission) is not GatewayQuotaAdmission
                )
            ):
                raise ValueError
            if (
                type(self.required_coverage) is not tuple
                or not self.required_coverage
                or any(type(item) is not AccountResourceKey for item in self.required_coverage)
                or len(set(self.required_coverage)) != len(self.required_coverage)
            ):
                raise ValueError
            if type(self.view_policies) is not tuple or any(
                type(item) is not GatewayAccountViewPolicy for item in self.view_policies
            ):
                raise ValueError
            policies = validate_policy_set(self.view_policies)
            coverage = frozenset(self.required_coverage)
            for policy in policies:
                if policy.view_scope == self.state_scope or not frozenset(
                    policy.resources
                ) <= coverage:
                    raise ValueError
            if type(self.require_open_orders) is not bool:
                raise ValueError
            for timeout in (
                self.refresh_interval_seconds,
                self.max_staleness_seconds,
                self.request_timeout_seconds,
            ):
                if (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not math.isfinite(float(timeout))
                    or float(timeout) <= 0
                ):
                    raise ValueError
            if not isinstance(self.principals, Mapping):
                raise ValueError
            copied_principals = dict(self.principals)
            if any(
                type(principal_ref) is not str
                or not principal_ref
                or type(principal) is not GatewayPrincipal
                or principal.principal_id != principal_ref
                for principal_ref, principal in copied_principals.items()
            ):
                raise ValueError
            account = self.account_scope
            if (
                account.journal_account_scope != account.journal_account_scope.strip()
                or not account.journal_account_scope
            ):
                raise ValueError
            object.__setattr__(self, "principals", MappingProxyType(copied_principals))
            object.__setattr__(self, "view_policies", policies)
            object.__setattr__(
                self,
                "_dispatch_quota_admission",
                None
                if effective_admission is None
                else GatewayQuotaDispatchAdmission(
                    effective_admission,
                    assert_domain_current=(
                        None
                        if self.quota_domain_binding is None
                        else self.quota_domain_binding.assert_current  # type: ignore[attr-defined]
                    ),
                ),
            )
        except GatewayOperatorDeploymentError:
            raise
        except BaseException:
            raise GatewayOperatorDeploymentError("INVALID_ACCOUNT_BINDING") from None

    @property
    def dispatch_quota_admission(
        self,
    ) -> Optional[Callable[[str, Optional[str], Optional[str], Optional[str], str, int], None]]:
        """Return the stable provider-neutral callback for trusted owner wiring.

        The callback uses the same local quota owner as the account provider
        session. Resource providers may explicitly inject it into Risk and
        Execution owners; GatewayOperator does not propagate it implicitly.
        """

        return self._dispatch_quota_admission

    @property
    def effective_quota_admission(self) -> object | None:
        """Return the one explicitly bound provider-domain admission owner."""

        if self.quota_domain_binding is not None:
            return self.quota_domain_binding.admission  # type: ignore[attr-defined]
        return self.quota_admission


class GatewayOperatorDeployment:
    """Compose and run the existing service-v2 Gateway Host on one owner thread.

    The operator creates ``ServiceConfig`` with ``parse_service_config`` and
    resolves ``TrustedServiceAuthority``, database/guard resources, and the
    session owner's secret resolver in trusted application code. No secrets or
    Python factories are loaded from the manifest or client request.
    """

    def __init__(
        self,
        config: ServiceConfig,
        authority: TrustedServiceAuthority,
        registry_path: str | Path,
        *,
        resource_provider: ServiceResourceProvider,
        session_owner: object | None = None,
        account_session: GatewayAccountSessionBinding | None = None,
        market_binding: GatewayMarketBinding | None = None,
        service_directory: Mapping[str, ServiceConfig] | None = None,
        trusted_clients: TrustedServiceClients | None = None,
        migration_deployment_epoch: str | None = None,
    ) -> None:
        if type(config) is not ServiceConfig:
            raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG")
        try:
            config.to_public_dict()
        except BaseException:
            raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG") from None
        if not callable(resource_provider):
            raise GatewayOperatorDeploymentError("INVALID_RESOURCE_PROVIDER")
        gateway = config.components.get("gateway")
        if not isinstance(gateway, Mapping):
            raise GatewayOperatorDeploymentError("GATEWAY_COMPONENT_REQUIRED")
        settings = gateway.get("settings")
        if not isinstance(settings, Mapping):
            raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG")
        options = settings.get("options")
        ports = settings.get("bind_ports")
        instance_id = settings.get("instance_id")
        if (
            not isinstance(options, Mapping)
            or type(instance_id) is not str
            or type(ports) not in (tuple, list)
        ):
            raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG")
        role = options.get("role")
        if role == "account_session_worker":
            session_ref = options.get("account_session_ref")
            if "service.provider_session" not in ports:
                raise GatewayOperatorDeploymentError("ACCOUNT_PROVIDER_SESSION_PORT_REQUIRED")
            if account_session is None:
                raise GatewayOperatorDeploymentError("ACCOUNT_SESSION_BINDING_REQUIRED")
            if type(account_session) is not GatewayAccountSessionBinding:
                raise GatewayOperatorDeploymentError("INVALID_ACCOUNT_BINDING")
            if account_session.account_session_ref != session_ref:
                raise GatewayOperatorDeploymentError("ACCOUNT_SESSION_REFERENCE_MISMATCH")
            if not callable(getattr(session_owner, "create_provider", None)):
                raise GatewayOperatorDeploymentError("ACCOUNT_SESSION_OWNER_REQUIRED")
            if market_binding is not None:
                raise GatewayOperatorDeploymentError("UNUSED_MARKET_BINDING")
            if "service.account_read" in ports:
                principal_refs = frozenset(authority.principals.values())
                if (
                    not account_session.principals
                    or not set(account_session.principals) <= principal_refs
                    or account_session.account_scope.execution_domain_ref
                    != authority.scope.execution_domain_ref
                    or any(
                        account_session.account_scope.journal_account_scope
                        not in principal.account_scopes
                        for principal in account_session.principals.values()
                    )
                ):
                    raise GatewayOperatorDeploymentError("ACCOUNT_PRINCIPAL_BINDING_INVALID")
            self._session_owner = session_owner
            self._account_session = account_session
            self._market_binding = None
        elif role == "market_hub":
            if account_session is not None or session_owner is not None:
                raise GatewayOperatorDeploymentError("UNUSED_ACCOUNT_SESSION_BINDING")
            if market_binding is None:
                raise GatewayOperatorDeploymentError("MARKET_BINDING_REQUIRED")
            if type(market_binding) is not GatewayMarketBinding:
                raise GatewayOperatorDeploymentError("INVALID_MARKET_BINDING")
            allowed_principals = market_binding.principal_allowed_keys
            self._market_binding = market_binding
            if frozenset(allowed_principals) != frozenset(authority.principals.values()):
                raise GatewayOperatorDeploymentError("MARKET_AUDIENCE_MISMATCH")
            self._session_owner = None
            self._account_session = None
        elif role == "trading_owner":
            if account_session is not None or session_owner is not None:
                raise GatewayOperatorDeploymentError("UNUSED_ACCOUNT_SESSION_BINDING")
            if market_binding is not None:
                raise GatewayOperatorDeploymentError("UNUSED_MARKET_BINDING")
            if (
                frozenset(ports) not in (
                    frozenset({"service.direct_write"}),
                    frozenset({"service.direct_write", "service.account_read"}),
                )
                or len(ports) != len(set(ports))
                or set(options) - {"role", "dispatch_enabled"}
                or type(options.get("dispatch_enabled", False)) is not bool
            ):
                raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG")
            self._session_owner = None
            self._account_session = None
            self._market_binding = None
        else:
            raise GatewayOperatorDeploymentError("UNSUPPORTED_GATEWAY_ROLE")

        self._config = config
        self._authority = authority
        self._resource_provider = resource_provider
        self._gateway_instance_id = instance_id
        self._gateway_role = role
        self._gateway_ports = frozenset(ports)
        self._registry_path = registry_path
        self._owner_thread_id: int | None = None
        self._account_worker: object | None = None
        self._unclaimed_providers: list[object] = []
        self._last_cleanup_code: str | None = None
        self._cleanup_lock = threading.Lock()
        self._host = ServiceHost(
            config,
            authority,
            registry_path,
            self._provide_resources,
            service_directory=service_directory,
            trusted_clients=trusted_clients,
            migration_deployment_epoch=migration_deployment_epoch,
        )

    @property
    def service_host(self) -> ServiceHost:
        """The composed Host for trusted operator observation/control."""

        return self._host

    @property
    def endpoint(self) -> str | None:
        return self._host.endpoint

    @property
    def market_endpoint(self) -> str | None:
        return self._host.market_endpoint

    @property
    def state(self) -> str:
        return self._host.state

    @property
    def gateway_role(self) -> str:
        return self._gateway_role

    @property
    def healthy(self) -> bool:
        """Current local Host readiness, not evidence of account authority."""

        self._check_owner_thread()
        return self._host.healthy

    @property
    def summary(self) -> Mapping[str, Any]:
        return self._host.summary

    @property
    def cleanup_status(self) -> Mapping[str, object]:
        """Finite cleanup facts; provider objects and references stay private."""

        with self._cleanup_lock:
            return MappingProxyType(
                {
                    "unclaimed_provider_count": len(self._unclaimed_providers),
                    "last_cleanup_code": self._last_cleanup_code,
                }
            )

    @property
    def account_session_worker(self) -> object | None:
        """Return the locally owned worker handle on its Host owner thread.

        This is an in-process operator capability. It is never exposed through
        ServiceHost, a client binding, or a wire response.
        """

        self._check_owner_thread()
        if self._gateway_role != "account_session_worker":
            raise GatewayOperatorDeploymentError("UNSUPPORTED_GATEWAY_ROLE")
        return self._account_worker

    @property
    def account_session_status(self) -> Mapping[str, object]:
        """Return finite worker state without provider or credential objects."""

        self._check_owner_thread()
        if self._gateway_role != "account_session_worker":
            raise GatewayOperatorDeploymentError("UNSUPPORTED_GATEWAY_ROLE")
        worker = self._account_worker
        if worker is None:
            return MappingProxyType(
                {
                    "state": "not_created",
                    "session_generation": None,
                    "ready": False,
                    "fresh_for_seconds": 0.0,
                }
            )
        try:
            status = worker.read_status()  # type: ignore[attr-defined]
            state = worker.state  # type: ignore[attr-defined]
            generation = worker.session_generation  # type: ignore[attr-defined]
            ready = status.get("ready")
            fresh_for = status.get("fresh_for_seconds")
            if (
                type(state) is not str
                or (generation is not None and type(generation) is not str)
                or type(ready) is not bool
                or isinstance(fresh_for, bool)
                or not isinstance(fresh_for, (int, float))
                or not math.isfinite(float(fresh_for))
                or float(fresh_for) < 0.0
            ):
                raise ValueError
            return MappingProxyType(
                {
                    "state": state,
                    "session_generation": generation,
                    "ready": ready,
                    "fresh_for_seconds": float(fresh_for),
                }
            )
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError(
                    "ACCOUNT_SESSION_WORKER_UNAVAILABLE"
                ) from None
            raise

    def recover_account_session(self) -> Mapping[str, object]:
        """Explicitly recover the account session on the Host owner thread.

        Recovery is local operator control only. The account worker closes and
        releases its current generation before it reacquires a generation and
        connects again; no account credential or provider object crosses the
        service-v2 protocol.
        """

        self._check_owner_thread()
        if self._gateway_role != "account_session_worker":
            raise GatewayOperatorDeploymentError("UNSUPPORTED_GATEWAY_ROLE")
        worker = self._account_worker
        if worker is None:
            raise GatewayOperatorDeploymentError("ACCOUNT_SESSION_WORKER_UNAVAILABLE")
        try:
            worker.recover()  # type: ignore[attr-defined]
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError(
                    "ACCOUNT_SESSION_RECOVERY_FAILED"
                ) from None
            raise
        return self.account_session_status

    def start(self) -> GatewayOperatorDeployment:
        """Start the existing Host on the caller's owner thread."""

        self._bind_owner_thread()
        self._host.start()
        return self

    def serve_once(self, timeout_ms: int = 0) -> bool:
        """Serve and maintain the Host on the same thread that started it."""

        self._check_owner_thread()
        return self._host.serve_once(timeout_ms)

    def close(self) -> None:
        """Close the Host on its owner thread, retaining normal Host uncertainty."""

        self._check_owner_thread()
        self._host.close()

    def serve_until_stopped(
        self, stop_event: object, *, poll_interval_ms: int = 100
    ) -> None:
        """Run the Host until a trusted local event is set, then close normally.

        Call this method from the dedicated service-owner thread. The stop
        event may be signalled by an operator control thread, but all Host
        lifecycle calls remain on this method's thread.
        """

        if not callable(getattr(stop_event, "is_set", None)):
            raise GatewayOperatorDeploymentError("INVALID_STOP_EVENT")
        if type(poll_interval_ms) is not int or not 1 <= poll_interval_ms <= 1_000:
            raise GatewayOperatorDeploymentError("INVALID_POLL_INTERVAL")
        self.start()
        try:
            while not stop_event.is_set():  # type: ignore[attr-defined]
                self.serve_once(poll_interval_ms)
        finally:
            if self._host.state not in {"closed", "failed"}:
                self.close()

    def retry_unclaimed_provider_cleanup(self) -> Mapping[str, int]:
        """Retry only providers retained before worker ownership was transferred."""

        self._check_owner_thread()
        with self._cleanup_lock:
            pending = tuple(self._unclaimed_providers)
            self._unclaimed_providers.clear()
        remaining: list[object] = []
        closed = 0
        for provider in pending:
            if _provider_close_confirmed(provider):
                closed += 1
            else:
                remaining.append(provider)
        with self._cleanup_lock:
            self._unclaimed_providers.extend(remaining)
            self._last_cleanup_code = (
                "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED" if remaining else None
            )
            return MappingProxyType({"closed": closed, "pending": len(remaining)})

    def _provide_resources(
        self,
        component: str,
        instance_id: str,
        options: Mapping[str, Any],
        scope: WireScope,
    ) -> ComponentResources:
        self._bind_owner_thread()
        if component != "gateway":
            return self._resource_provider(component, instance_id, options, scope)
        if instance_id != self._gateway_instance_id or options.get("role") != self._gateway_role:
            raise GatewayOperatorDeploymentError("INVALID_DEPLOYMENT_CONFIG")
        if self._gateway_role == "market_hub":
            return self._build_market_resources(scope)
        if self._gateway_role == "trading_owner":
            return self._resource_provider(component, instance_id, options, scope)
        return self._build_account_resources(options)

    def _build_market_resources(self, scope: WireScope) -> ComponentResources:
        binding = self._market_binding
        if type(binding) is not GatewayMarketBinding or type(scope) is not WireScope:
            raise GatewayOperatorDeploymentError("INVALID_MARKET_BINDING")
        provider: object | None = None
        history_provider: object | None = None
        hub: object | None = None
        cleanup_callback: Callable[[], None] | None = None
        ownership_transferred = False
        try:
            from bt_api_gateway.market_hub import GatewayMarketHub

            provider = binding.provider_factory()
            if not callable(getattr(provider, "subscribe", None)) or not callable(
                getattr(provider, "unsubscribe", None)
            ):
                raise TypeError("market provider does not implement the Gateway provider port")
            key_universe = frozenset(binding.key_universe)
            principal_allowed_keys = binding.principal_allowed_keys
            max_provider_events = binding.max_provider_events_per_maintain
            history_key_universe = binding.history_key_universe
            principal_allowed_history_keys = binding.principal_allowed_history_keys
            history_timeout_seconds = binding.history_timeout_seconds
            if binding.history_provider_factory is not None:
                history_provider = binding.history_provider_factory()
                if not callable(getattr(history_provider, "fetch", None)):
                    raise TypeError(
                        "history provider does not implement the Gateway history port"
                    )
            if history_provider is provider:
                history_provider = None
                raise TypeError("stream and history providers must have separate ownership")
            hub = GatewayMarketHub(
                provider,
                key_universe=key_universe,
                principal_allowed_keys=principal_allowed_keys,
                service_identity=self._authority.identity,
                service_scope=self._authority.scope,
                max_provider_events_per_maintain=max_provider_events,
                history_provider=history_provider,
                history_timeout_seconds=history_timeout_seconds,
                history_key_universe=(history_key_universe or None),
                principal_allowed_history_keys=(
                    principal_allowed_history_keys or None
                ),
            )

            hub_closed = False
            history_provider_closed = history_provider is None
            provider_closed = provider is None

            def close_market_resources() -> None:
                nonlocal hub_closed, history_provider_closed, provider_closed
                hub_error: BaseException | None = None
                if not hub_closed:
                    try:
                        hub.close()  # type: ignore[attr-defined]
                        hub_closed = True
                    except BaseException as exc:
                        hub_error = exc
                history_error: BaseException | None = None
                if history_provider is not None and not history_provider_closed:
                    try:
                        _close_market_history_provider(history_provider)
                        history_provider_closed = True
                    except BaseException as exc:
                        history_error = exc
                provider_error: BaseException | None = None
                if hub_closed and not provider_closed:
                    try:
                        _close_market_provider(provider)
                        provider_closed = True
                    except BaseException as exc:
                        provider_error = exc
                if hub_error is not None:
                    raise hub_error
                if history_error is not None:
                    raise history_error
                if provider_error is not None:
                    raise provider_error

            cleanup_callback = close_market_resources
            resources = ComponentResources.owned(
                {"hub": hub},
                ready=lambda: hub.ready is True,
                close=close_market_resources,
            )
            ownership_transferred = True
            return resources
        except BaseException as exc:
            cleanup_failed = False
            if not ownership_transferred and hub is not None:
                if cleanup_callback is None:
                    self._retain_unclaimed_provider(hub)
                    cleanup_failed = True
                else:
                    try:
                        cleanup_callback()
                    except BaseException:
                        self._retain_unclaimed_provider(
                            _RetryableMarketCleanup(cleanup_callback)
                        )
                        cleanup_failed = True
            elif not ownership_transferred:
                if history_provider is not None:
                    try:
                        _close_market_history_provider(history_provider)
                    except BaseException:
                        self._retain_unclaimed_provider(history_provider)
                        cleanup_failed = True
                if provider is not None and provider is not history_provider:
                    try:
                        _close_market_provider(provider)
                    except BaseException:
                        self._retain_unclaimed_provider(provider)
                        cleanup_failed = True
            if cleanup_failed and isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError(
                    "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED"
                ) from None
            if isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError("MARKET_HUB_BUILD_FAILED") from None
            raise

    def _retain_unclaimed_provider(self, provider: object) -> None:
        with self._cleanup_lock:
            if all(current is not provider for current in self._unclaimed_providers):
                self._unclaimed_providers.append(provider)
            self._last_cleanup_code = "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED"

    def _build_account_resources(self, options: Mapping[str, Any]) -> ComponentResources:
        binding = self._account_session
        owner = self._session_owner
        if (
            type(binding) is not GatewayAccountSessionBinding
            or owner is None
            or options.get("account_session_ref") != binding.account_session_ref
        ):
            raise GatewayOperatorDeploymentError("ACCOUNT_SESSION_BINDING_REQUIRED")
        try:
            provider = owner.create_provider(binding.account_session_ref)  # type: ignore[attr-defined]
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError(
                    "ACCOUNT_PROVIDER_RESOLUTION_FAILED"
                ) from None
            raise

        try:
            from bt_api_gateway.account_session_worker import GatewayAccountSessionWorker

            if binding.effective_quota_admission is not None:
                from bt_api_gateway.quota_admission import (
                    GatewayQuotaProviderSession,
                    GatewayQuotaSubject,
                )

                provider = GatewayQuotaProviderSession(
                    provider,
                    binding.effective_quota_admission,  # type: ignore[arg-type]
                    GatewayQuotaSubject(account_ref=binding.account_scope.account_ref),
                    assert_session_owned=binding.guard.assert_owned,
                    assert_domain_current=(
                        None
                        if binding.quota_domain_binding is None
                        else binding.quota_domain_binding.assert_current  # type: ignore[attr-defined]
                    ),
                )

            worker = GatewayAccountSessionWorker(
                provider,
                binding.journal,
                account_key=binding.account_key,
                journal_account_scope=binding.account_scope.journal_account_scope,
                state_scope=binding.state_scope,
                guard=binding.guard,
                required_coverage=binding.required_coverage,
                view_policies=binding.view_policies,
                require_open_orders=binding.require_open_orders,
                refresh_interval_seconds=binding.refresh_interval_seconds,
                max_staleness_seconds=binding.max_staleness_seconds,
                request_timeout_seconds=binding.request_timeout_seconds,
            )
            values: dict[str, object] = {}
            if "service.account_read" in self._gateway_ports:
                values = {
                    "journal": binding.journal,
                    "accounts": {binding.account_scope.account_ref: binding.account_scope},
                    "principals": binding.principals,
                }
            internal_ports: dict[str, object] = {}
            if "service.provider_session" in self._gateway_ports:
                internal_ports["service.provider_session"] = worker
            resources = ComponentResources.owned(
                values,
                ready=lambda: worker.ready is True,
                close=worker.close,
                internal_ports=internal_ports,
            )
            self._account_worker = worker
            return resources
        except BaseException as exc:
            confirmed = _provider_close_confirmed(provider)
            if not confirmed:
                with self._cleanup_lock:
                    self._unclaimed_providers.append(provider)
                    self._last_cleanup_code = "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED"
                if isinstance(exc, Exception):
                    raise GatewayOperatorDeploymentError(
                        "UNCLAIMED_PROVIDER_CLOSE_UNCONFIRMED"
                    ) from None
                raise
            if isinstance(exc, Exception):
                raise GatewayOperatorDeploymentError("ACCOUNT_WORKER_BUILD_FAILED") from None
            raise

    def _bind_owner_thread(self) -> None:
        current = threading.get_ident()
        if self._owner_thread_id is None:
            self._owner_thread_id = current
        elif self._owner_thread_id != current:
            raise GatewayOperatorDeploymentError("OWNER_THREAD_REQUIRED")

    def _check_owner_thread(self) -> None:
        if self._owner_thread_id is None or self._owner_thread_id != threading.get_ident():
            raise GatewayOperatorDeploymentError("OWNER_THREAD_REQUIRED")


def _provider_close_confirmed(provider: object) -> bool:
    try:
        close = getattr(provider, "close", None)
        if not callable(close):
            return False
        result = close()
        return result is None or result is True
    except BaseException:
        return False


def _valid_ref(value: object) -> bool:
    return type(value) is str and _SAFE_REF.fullmatch(value) is not None


def _close_market_provider(provider: object) -> None:
    """Retry provider-owned partial-start cleanup after Hub handle release."""
    close = getattr(provider, "close", None)
    if not callable(close):
        return
    try:
        result = close()
    except Exception:
        raise GatewayOperatorDeploymentError("MARKET_PROVIDER_CLOSE_UNCONFIRMED") from None
    if result is False:
        raise GatewayOperatorDeploymentError("MARKET_PROVIDER_CLOSE_UNCONFIRMED")


def _close_market_history_provider(provider: object) -> None:
    """Close an optional operator-owned history client after the Hub stops."""
    close = getattr(provider, "close", None)
    if not callable(close):
        return
    try:
        result = close()
    except Exception:
        raise GatewayOperatorDeploymentError(
            "MARKET_HISTORY_PROVIDER_CLOSE_UNCONFIRMED"
        ) from None
    if result is False or (result is not None and result is not True):
        raise GatewayOperatorDeploymentError("MARKET_HISTORY_PROVIDER_CLOSE_UNCONFIRMED")


__all__ = [
    "GatewayAccountSessionBinding",
    "GatewayMarketBinding",
    "GatewayOperatorDeployment",
    "GatewayOperatorDeploymentError",
]
