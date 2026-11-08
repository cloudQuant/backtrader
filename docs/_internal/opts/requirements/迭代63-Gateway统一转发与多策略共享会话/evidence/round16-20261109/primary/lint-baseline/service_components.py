"""Fixed, lazy factories for the SDK's selected service components.

This module contains no domain-package imports at module load time.  A
component package is imported only when its fixed name appears in a parsed
service manifest.  The manifest can select a built-in component; it cannot
name Python modules, factories, handlers, or backend objects.

The current runtime exposes implemented read adapters and explicitly
selected monitor ingress roles. Other manifest ports are either
internal objects supplied by the trusted resource provider or fail closed
before the listener is opened.
"""

from __future__ import annotations

import dataclasses
import errno
import importlib
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol

from bt_api_base.account_protocol import AccountResourceKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope

from .service_registry import (
    AccountRiskPolicyBinding,
    ActiveRegistrationContext,
    ServiceCallContext,
    ServiceCapability,
    ServiceOperationDeniedError,
    ServiceResultTooLargeError,
    TrustedGroupReservationPolicy,
    TrustedGroupResolutionPolicy,
    TrustedGroupWritePolicy,
)

if TYPE_CHECKING:
    from bt_api_risk.core.admission import AccountScope
    from .service_risk_order_entry import RiskOrderTarget


class ServiceComponentError(ValueError):
    """Finite component-construction error without resource or config values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResourceOwnership(str, Enum):  # noqa: UP042 -- Python 3.9 compatibility.
    """Whether a trusted provider resource is owned by the host."""

    OWNED = "owned"
    BORROWED = "borrowed"


@dataclass(frozen=True, slots=True)
class TrustedRiskPolicyBinding:
    """Trusted alias from a configured reference to one actual Risk policy.

    The policy object is resolved by the operator resource provider and must
    be the exact object exposed by the gate passed to the Risk adapter.
    """

    reference: str
    scope: WireScope
    policy: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.reference) is not str
            or not self.reference
            or self.reference != self.reference.strip()
            or len(self.reference.encode("utf-8", errors="strict")) > 128
        ):
            raise ServiceComponentError("INVALID_RISK_POLICY_BINDING")
        if type(self.scope) is not WireScope or self.scope.run_id is not None:
            raise ServiceComponentError("INVALID_RISK_POLICY_BINDING")
        if self.policy is None:
            raise ServiceComponentError("INVALID_RISK_POLICY_BINDING")


@dataclass(frozen=True, slots=True)
class TrustedSharedCollateralDomain:
    """Operator-resolved collateral-domain declaration for one Host.

    The manifest labels and expected members describe the trusted deployment
    configuration; they do not authenticate an owner.  ``owner_gate`` and
    every target in ``member_targets`` are object-identity pins supplied by
    the trusted resource provider and are checked against the fully built
    component graph before the Registry or listener starts.
    """

    domain_id: str
    revision: str
    member_scopes: tuple[AccountScope, ...]
    member_targets: tuple[tuple[WireScope, RiskOrderTarget], ...]
    max_notional: Decimal | None
    owner_instance_id: str | None
    owner_gate: object | None = field(default=None, repr=False, compare=False)


class BorrowedServiceClient:
    """Call-only view of the Host's already-started upstream runtime.

    The Host retains lifecycle ownership. Component adapters receive no
    ``start``, ``maintain``, ``close`` or recovery API, and this facade is
    pinned to the constructing owner thread.
    """

    __slots__ = ("_runtime", "_owner_thread")

    def __init__(self, runtime: object) -> None:
        call = getattr(runtime, "call", None)
        state = getattr(runtime, "state", None)
        if not callable(call) or state != "registered":
            raise ServiceComponentError("UPSTREAM_CLIENT_NOT_READY")
        try:
            healthy = runtime.healthy  # type: ignore[attr-defined]
        except Exception:
            healthy = False
        if healthy is not True:
            raise ServiceComponentError("UPSTREAM_CLIENT_NOT_READY")
        self._runtime = runtime
        self._owner_thread = threading.get_ident()

    def call(
        self,
        mount: str,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        account_ref: str | None = None,
        portfolio_ref: str | None = None,
        scope_ref: str | None = None,
        max_reply_message_bytes: int | None = None,
    ) -> Mapping[str, Any]:
        if threading.get_ident() != self._owner_thread:
            raise ServiceComponentError("OWNER_THREAD_REQUIRED")
        return self._runtime.call(  # type: ignore[attr-defined, no-any-return]
            mount,
            operation,
            arguments,
            account_ref=account_ref,
            portfolio_ref=portfolio_ref,
            scope_ref=scope_ref,
            max_reply_message_bytes=max_reply_message_bytes,
        )


def _borrowed_noop() -> None:
    """Explicit release callback for resources whose lifetime is borrowed."""


@dataclass(frozen=True, slots=True)
class ComponentResources:
    """Trusted resources resolved by the operator when a host starts.

    ``values`` contains only the exact constructor inputs for the selected
    built-in adapter. ``internal_ports`` contains trusted in-process objects;
    these are never converted into RPC capabilities. Borrowed resources must
    be created with :meth:`borrowed`, which installs an explicit no-op release
    callback. Owned resources require a provider-supplied close callback. An
    owned callback must be safe to retry if it raises; the host retains that
    resource and may call it again during a later cleanup attempt.
    """

    values: Mapping[str, object]
    ready: Callable[[], bool] = field(repr=False, compare=False)
    close_resource: Callable[[], None] = field(repr=False, compare=False)
    internal_ports: Mapping[str, object] = field(default_factory=dict)
    ownership: ResourceOwnership = ResourceOwnership.BORROWED
    risk_policy_bindings: tuple[TrustedRiskPolicyBinding, ...] = ()
    shared_collateral_domains: tuple[TrustedSharedCollateralDomain, ...] = ()
    maintain: Callable[[frozenset[str]], object] | None = field(
        default=None, repr=False, compare=False
    )
    next_maintenance_delay: Callable[[], float | None] | None = field(
        default=None, repr=False, compare=False
    )
    operation_readiness: Mapping[str, Callable[[], bool]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _release_once: Callable[[], None] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        values = _copy_string_mapping(self.values, "INVALID_RESOURCE_VALUES")
        internal = _copy_string_mapping(self.internal_ports, "INVALID_INTERNAL_PORTS")
        operation_readiness = _copy_callable_mapping(
            self.operation_readiness, "INVALID_OPERATION_READINESS"
        )
        if not set(operation_readiness) <= set(_RESTRICTED_OPERATION_PORTS):
            raise ServiceComponentError("INVALID_OPERATION_READINESS")
        if not callable(self.ready):
            raise ServiceComponentError("INVALID_READINESS_CHECK")
        if type(self.ownership) is not ResourceOwnership:
            raise ServiceComponentError("INVALID_RESOURCE_OWNERSHIP")
        if not callable(self.close_resource):
            raise ServiceComponentError("INVALID_RESOURCE_CLOSE")
        if self.maintain is not None and not callable(self.maintain):
            raise ServiceComponentError("INVALID_RESOURCE_MAINTENANCE")
        if self.next_maintenance_delay is not None and not callable(
            self.next_maintenance_delay
        ):
            raise ServiceComponentError("INVALID_RESOURCE_MAINTENANCE")
        if type(self.risk_policy_bindings) is not tuple or any(
            type(binding) is not TrustedRiskPolicyBinding
            for binding in self.risk_policy_bindings
        ):
            raise ServiceComponentError("INVALID_RISK_POLICY_BINDING")
        if type(self.shared_collateral_domains) is not tuple or any(
            type(domain) is not TrustedSharedCollateralDomain
            for domain in self.shared_collateral_domains
        ):
            raise ServiceComponentError("INVALID_SHARED_COLLATERAL_DECLARATION")
        if self.ownership is ResourceOwnership.BORROWED:
            if self.close_resource is not _borrowed_noop:
                raise ServiceComponentError("BORROWED_RESOURCE_REQUIRES_EXPLICIT_NOOP")
        elif self.close_resource is _borrowed_noop:
            raise ServiceComponentError("OWNED_RESOURCE_REQUIRES_CLOSE")

        object.__setattr__(self, "values", MappingProxyType(values))
        object.__setattr__(self, "internal_ports", MappingProxyType(internal))
        object.__setattr__(
            self, "operation_readiness", MappingProxyType(operation_readiness)
        )
        close = self.close_resource
        closed = False
        close_lock = threading.Lock()

        def release_once() -> None:
            nonlocal closed
            with close_lock:
                if closed:
                    return
                close()
                closed = True

        object.__setattr__(self, "_release_once", release_once)

    @classmethod
    def borrowed(
        cls,
        values: Mapping[str, object],
        *,
        ready: Callable[[], bool],
        internal_ports: Mapping[str, object] | None = None,
        risk_policy_bindings: tuple[TrustedRiskPolicyBinding, ...] = (),
        shared_collateral_domains: tuple[TrustedSharedCollateralDomain, ...] = (),
        operation_readiness: Mapping[str, Callable[[], bool]] | None = None,
        maintain: Callable[[frozenset[str]], object] | None = None,
        next_maintenance_delay: Callable[[], float | None] | None = None,
    ) -> ComponentResources:
        """Describe operator-owned objects whose lifetime remains external."""

        return cls(
            values=values,
            ready=ready,
            internal_ports={} if internal_ports is None else internal_ports,
            ownership=ResourceOwnership.BORROWED,
            risk_policy_bindings=risk_policy_bindings,
            shared_collateral_domains=shared_collateral_domains,
            operation_readiness=(
                {} if operation_readiness is None else operation_readiness
            ),
            maintain=maintain,
            next_maintenance_delay=next_maintenance_delay,
            close_resource=_borrowed_noop,
        )

    @classmethod
    def owned(
        cls,
        values: Mapping[str, object],
        *,
        ready: Callable[[], bool],
        close: Callable[[], None],
        internal_ports: Mapping[str, object] | None = None,
        risk_policy_bindings: tuple[TrustedRiskPolicyBinding, ...] = (),
        shared_collateral_domains: tuple[TrustedSharedCollateralDomain, ...] = (),
        operation_readiness: Mapping[str, Callable[[], bool]] | None = None,
        maintain: Callable[[frozenset[str]], object] | None = None,
        next_maintenance_delay: Callable[[], float | None] | None = None,
    ) -> ComponentResources:
        """Describe host-owned objects and their explicit cleanup callback."""

        return cls(
            values=values,
            ready=ready,
            internal_ports={} if internal_ports is None else internal_ports,
            ownership=ResourceOwnership.OWNED,
            risk_policy_bindings=risk_policy_bindings,
            shared_collateral_domains=shared_collateral_domains,
            operation_readiness=(
                {} if operation_readiness is None else operation_readiness
            ),
            maintain=maintain,
            next_maintenance_delay=next_maintenance_delay,
            close_resource=close,
        )

    def close(self) -> None:
        """Release owned resources once; borrowed resources use their no-op."""

        self._release_once()


class ServiceResourceConstructionError(ServiceComponentError):
    """Carry partial owned resources when trusted provider bootstrap fails.

    The finite exception message contains no resource values. The build caller
    must retain these exact resources until their normal close succeeds.
    """

    def __init__(self, resources: ComponentResources) -> None:
        if type(resources) is not ComponentResources or (
            resources.ownership is not ResourceOwnership.OWNED
        ):
            raise ServiceComponentError("INVALID_PARTIAL_COMPONENT_RESOURCES")
        self.resources = resources
        super().__init__("RESOURCE_CONSTRUCTION_FAILED")


class ServiceResourceProvider(Protocol):
    """Trusted operator hook for fixed component resources, called at start."""

    def __call__(
        self,
        component: str,
        instance_id: str,
        options: Mapping[str, object],
        scope: WireScope,
    ) -> ComponentResources:
        """Resolve trusted resources for one selected manifest instance."""


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """One normalized parser-created component selection."""

    component: str
    instance_id: str
    bind_ports: tuple[str, ...]
    options: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.component) is not str or type(self.instance_id) is not str:
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        if type(self.bind_ports) is not tuple or not self.bind_ports:
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        if any(type(port) is not str for port in self.bind_ports):
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        if not isinstance(self.options, Mapping):
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class PreparedComponent:
    """A selected component whose pure package options check has passed."""

    spec: ComponentSpec
    options: Mapping[str, object]
    module: object = field(repr=False, compare=False)
    operations_by_port: Mapping[str, frozenset[str]]
    write_operations_by_port: Mapping[str, frozenset[str]]


@dataclass(frozen=True, slots=True)
class ServiceComponent:
    """A concrete component with exact public handlers and internal objects."""

    component: str
    instance_id: str
    capabilities: tuple[ServiceCapability, ...]
    handlers: Mapping[
        str,
        Callable[[ServiceCallContext, Mapping[str, Any]], Mapping[str, Any]],
    ]
    internal_ports: Mapping[str, object]
    readiness: Callable[[], bool] = field(repr=False, compare=False)
    close: Callable[[], None] = field(repr=False, compare=False)
    maintain: Callable[[frozenset[str]], object] | None = field(
        default=None, repr=False, compare=False
    )
    maintain_registrations: Callable[[tuple[ActiveRegistrationContext, ...]], object] | None = (
        field(default=None, repr=False, compare=False)
    )
    maintain_resources: Callable[[frozenset[str]], object] | None = field(
        default=None, repr=False, compare=False
    )
    next_maintenance_delay: Callable[[], float | None] | None = field(
        default=None, repr=False, compare=False
    )
    account_risk_policy_bindings: tuple[AccountRiskPolicyBinding, ...] = ()
    account_risk_policy_required_ports: frozenset[str] = frozenset()
    shared_collateral_domains: tuple[TrustedSharedCollateralDomain, ...] = field(
        default=(), repr=False, compare=False
    )
    risk_owner_gate: object | None = field(default=None, repr=False, compare=False)
    risk_owner_targets: Mapping[WireScope, object] = field(
        default_factory=dict, repr=False, compare=False
    )
    risk_owner_admission: Mapping[WireScope, object] = field(
        default_factory=dict, repr=False, compare=False
    )
    operation_readiness: Mapping[str, Callable[[], bool]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.capabilities) is not tuple or any(
            type(capability) is not ServiceCapability for capability in self.capabilities
        ):
            raise ServiceComponentError("INVALID_COMPONENT_CAPABILITIES")
        if any(capability.instance_id != self.instance_id for capability in self.capabilities):
            raise ServiceComponentError("INVALID_COMPONENT_CAPABILITIES")
        handlers = _copy_callable_mapping(self.handlers, "INVALID_COMPONENT_HANDLERS")
        operation_readiness = _copy_callable_mapping(
            self.operation_readiness, "INVALID_OPERATION_READINESS"
        )
        if not set(operation_readiness) <= set(_RESTRICTED_OPERATION_PORTS):
            raise ServiceComponentError("INVALID_OPERATION_READINESS")
        declared = frozenset(
            operation for capability in self.capabilities for operation in capability.operations
        )
        write_operations = frozenset(
            operation
            for capability in self.capabilities
            for operation in capability.write_operations
        )
        if set(handlers) != set(declared):
            raise ServiceComponentError("HANDLER_CAPABILITY_MISMATCH")
        if not set(operation_readiness).issubset(write_operations):
            raise ServiceComponentError("INVALID_OPERATION_READINESS")
        for operation in operation_readiness:
            expected_port = _RESTRICTED_OPERATION_PORTS[operation]
            routes = tuple(
                capability
                for capability in self.capabilities
                if operation in capability.operations
            )
            if not routes or any(
                capability.port != expected_port
                or operation not in capability.write_operations
                for capability in routes
            ):
                raise ServiceComponentError("INVALID_OPERATION_READINESS")
        internal = _copy_string_mapping(self.internal_ports, "INVALID_INTERNAL_PORTS")
        if not callable(self.readiness) or not callable(self.close):
            raise ServiceComponentError("INVALID_COMPONENT_LIFECYCLE")
        if self.maintain is not None and not callable(self.maintain):
            raise ServiceComponentError("INVALID_COMPONENT_LIFECYCLE")
        if self.maintain_registrations is not None and not callable(self.maintain_registrations):
            raise ServiceComponentError("INVALID_COMPONENT_LIFECYCLE")
        if self.maintain_resources is not None and not callable(self.maintain_resources):
            raise ServiceComponentError("INVALID_COMPONENT_LIFECYCLE")
        if self.next_maintenance_delay is not None and not callable(
            self.next_maintenance_delay
        ):
            raise ServiceComponentError("INVALID_COMPONENT_LIFECYCLE")
        if type(self.account_risk_policy_bindings) is not tuple or any(
            type(binding) is not AccountRiskPolicyBinding
            for binding in self.account_risk_policy_bindings
        ):
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        if type(self.account_risk_policy_required_ports) is not frozenset or any(
            type(port) is not str or not port for port in self.account_risk_policy_required_ports
        ):
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        capability_ports = {capability.port for capability in self.capabilities}
        if not self.account_risk_policy_required_ports.issubset(capability_ports):
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        if any(binding.instance_id != self.instance_id for binding in self.account_risk_policy_bindings):
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        binding_scopes = [binding.scope for binding in self.account_risk_policy_bindings]
        if len(binding_scopes) != len(set(binding_scopes)):
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        if self.account_risk_policy_required_ports - {"service.order_entry"}:
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        if self.account_risk_policy_required_ports and not self.account_risk_policy_bindings:
            raise ServiceComponentError("INVALID_ACCOUNT_RISK_POLICY_BINDINGS")
        if type(self.shared_collateral_domains) is not tuple or any(
            type(domain) is not TrustedSharedCollateralDomain
            for domain in self.shared_collateral_domains
        ):
            raise ServiceComponentError("INVALID_SHARED_COLLATERAL_DECLARATION")
        if not isinstance(self.risk_owner_targets, Mapping) or not isinstance(
            self.risk_owner_admission, Mapping
        ):
            raise ServiceComponentError("INVALID_SHARED_COLLATERAL_OWNER")
        owner_targets = dict(self.risk_owner_targets)
        owner_admission = dict(self.risk_owner_admission)
        if any(
            type(scope) is not WireScope or target is None
            for scope, target in owner_targets.items()
        ) or any(
            type(scope) is not WireScope or admission is None
            for scope, admission in owner_admission.items()
        ):
            raise ServiceComponentError("INVALID_SHARED_COLLATERAL_OWNER")
        if self.risk_owner_gate is None:
            if owner_targets or owner_admission:
                raise ServiceComponentError("INVALID_SHARED_COLLATERAL_OWNER")
        elif not owner_targets or set(owner_targets) != set(owner_admission):
            raise ServiceComponentError("INVALID_SHARED_COLLATERAL_OWNER")
        object.__setattr__(self, "handlers", MappingProxyType(handlers))
        object.__setattr__(self, "internal_ports", MappingProxyType(internal))
        object.__setattr__(
            self, "operation_readiness", MappingProxyType(operation_readiness)
        )
        object.__setattr__(self, "risk_owner_targets", MappingProxyType(owner_targets))
        object.__setattr__(self, "risk_owner_admission", MappingProxyType(owner_admission))


@dataclass(frozen=True, slots=True)
class _Builtin:
    module_name: str
    operations_attribute: tuple[str, ...]
    resource_keys: frozenset[str]
    public_ports: Mapping[str, frozenset[str]]
    internal_ports: frozenset[str]
    write_operations_by_port: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    validator_module_name: str | None = None
    optional_resource_keys: frozenset[str] = frozenset()


_RECOVERY_CLOSE_OPERATION: Final[str] = "orders.submit_recovery_close"
_OWNER_CANCEL_OPERATION: Final[str] = "owner.cancel"
_RESTRICTED_OPERATION_PORTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        _RECOVERY_CLOSE_OPERATION: "service.order_entry",
        _OWNER_CANCEL_OPERATION: "service.owner_control",
    }
)


_BUILTINS: Mapping[str, _Builtin] = MappingProxyType(
    {
        "gateway": _Builtin(
            module_name="bt_api_gateway.service_component",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"journal", "accounts", "principals"}),
            public_ports=MappingProxyType(
                {
                    "service.account_read": frozenset(
                        {
                            "account.read_after",
                            "account.snapshot",
                            "account.snapshot.typed",
                            "account.head",
                            "account.ack",
                            "account.progress",
                            "account.configuration",
                            "account.server_time_probe",
                            "account.instrument_metadata",
                            "account.reconciliation_cut",
                        }
                    )
                }
            ),
            internal_ports=frozenset(
                {"service.provider_session", "service.owner_control", "service.reconciliation"}
            ),
        ),
        "execution": _Builtin(
            module_name="bt_api_execution.service_component",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"store", "targets"}),
            public_ports=MappingProxyType({"service.order_query": frozenset({"orders.query"})}),
            internal_ports=frozenset({"service.owner_control"}),
        ),
        "monitor": _Builtin(
            module_name="bt_api_monitor.service_component",
            operations_attribute=("MONITOR_READ_OPERATIONS",),
            resource_keys=frozenset({"outbox", "targets"}),
            public_ports=MappingProxyType(
                {"service.monitor_query": frozenset({"monitor.query", "monitor.read_after"})}
            ),
            internal_ports=frozenset(),
        ),
        "risk": _Builtin(
            module_name="bt_api_risk.service_component",
            operations_attribute=("RiskReadService", "SUPPORTED_OPERATIONS"),
            resource_keys=frozenset({"gate", "targets"}),
            public_ports=MappingProxyType({"service.risk_query": frozenset({"risk.snapshot"})}),
            internal_ports=frozenset(
                {
                    "service.group_reservations",
                    "service.order_admission",
                    "service.owner_control",
                    "service.group_admission",
                }
            ),
        ),
    }
)

_ROLE_BUILTINS: Mapping[tuple[str, str], _Builtin] = MappingProxyType(
    {
        ("gateway", "trading_owner"): _Builtin(
            module_name="bt_api_py.gateway_direct_service",
            operations_attribute=("TRADING_OPERATIONS",),
            resource_keys=frozenset({"binding"}),
            public_ports=MappingProxyType(
                {
                    "service.direct_write": frozenset(
                        {"direct.reserve", "direct.release", "direct.command_status", "direct.dispatch",
                         "direct.events.read_after", "direct.events.progress", "direct.events.ack"}
                    ),
                    "service.account_read": frozenset(
                        {
                            "account.snapshot", "account.snapshot.typed", "account.head",
                            "account.read_after", "account.ack", "account.progress",
                        }
                    ),
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {"service.direct_write": frozenset({"direct.reserve", "direct.release", "direct.dispatch"})}
            ),
        ),
        (
            "gateway",
            "market_hub",
        ): _Builtin(
            module_name="bt_api_gateway.market_hub",
            operations_attribute=("ALL_MARKET_OPERATIONS_WITH_BOUNDED_READ_AFTER",),
            resource_keys=frozenset({"hub"}),
            public_ports=MappingProxyType(
                {
                    "service.market_source": frozenset(
                        {
                            "market.bootstrap_many",
                            "market.subscribe",
                            "market.unsubscribe",
                            "market.snapshot",
                            "market.head",
                            "market.read_after",
                            "market.read_after_bounded",
                            "market.history",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            validator_module_name="bt_api_gateway.service_component",
        ),
        (
            "monitor",
            "durable_ingress",
        ): _Builtin(
            module_name="bt_api_monitor.service_ingress",
            operations_attribute=("MONITOR_INGRESS_OPERATIONS",),
            resource_keys=frozenset({"outbox", "targets"}),
            public_ports=MappingProxyType(
                {"service.telemetry_ingress": frozenset({"events.append"})}
            ),
            internal_ports=frozenset(),
        ),
        ("monitor", "telemetry_ingress"): _Builtin(
            module_name="bt_api_monitor.service_telemetry",
            operations_attribute=("TELEMETRY_OPERATIONS",),
            resource_keys=frozenset({"targets"}),
            public_ports=MappingProxyType(
                {
                    "service.telemetry_ingress": frozenset({"telemetry.append"}),
                    "service.monitor_query": frozenset({"telemetry.snapshot"}),
                }
            ),
            internal_ports=frozenset(),
        ),
        ("monitor", "control"): _Builtin(
            module_name="bt_api_py.service_monitor_control",
            operations_attribute=("MonitorControlRuntime", "PUBLIC_OPERATIONS"),
            resource_keys=frozenset({"service", "owners"}),
            public_ports=MappingProxyType(
                {
                    "service.monitor_control": frozenset(
                        {"monitor.control", "monitor.control_status"}
                    )
                }
            ),
            internal_ports=frozenset(),
            validator_module_name="bt_api_monitor.service_control",
        ),
        ("execution", "account_owner"): _Builtin(
            module_name="bt_api_py.service_execution_account_books",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"store", "targets", "dispatch", "admission"}),
            optional_resource_keys=frozenset(
                {"cancel_dispatch", "cancel_before_dispatch", "borrowed_writer_lease"}
            ),
            public_ports=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.cancel",
                            "orders.submit_approved_target",
                            _RECOVERY_CLOSE_OPERATION,
                        }
                    ),
                    "service.order_query": frozenset(
                        {"orders.query", "execution.account_books.query"}
                    ),
                    "service.owner_control": frozenset({"owner.cancel", "owner.reduce"}),
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.cancel",
                            "orders.submit_approved_target",
                            _RECOVERY_CLOSE_OPERATION,
                        }
                    ),
                    "service.owner_control": frozenset({"owner.cancel", "owner.reduce"}),
                }
            ),
            # The SDK wrapper delegates to bt_api_execution's closed role
            # validator and adds the SDK ``command_bindings`` option (R2-B).
            validator_module_name="bt_api_py.service_execution_account_books",
        ),
        ("execution", "group_account_owner"): _Builtin(
            module_name="bt_api_py.service_execution_group",
            operations_attribute=("GROUP_ACCOUNT_OWNER_OPERATIONS",),
            resource_keys=frozenset(
                {
                    "store",
                    "dispatch",
                    "accepted_group_store",
                    "group_authority",
                    "group_runtime_bundle",
                }
            ),
            public_ports=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit_group_leg",
                            "orders.resolve_group_leg",
                            "orders.cancel_group_leg",
                        }
                    ),
                    "service.order_query": frozenset(
                        {"orders.query_group_leg", "orders.query_group_cancel"}
                    ),
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit_group_leg",
                            "orders.resolve_group_leg",
                            "orders.cancel_group_leg",
                        }
                    )
                }
            ),
        ),
        ("execution", "account_group_owner"): _Builtin(
            module_name="bt_api_py.service_execution_account_group_owner",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset(
                {
                    "store",
                    "targets",
                    "dispatch",
                    "admission",
                    "accepted_group_store",
                    "group_authority",
                    "group_runtime_bundle",
                }
            ),
            optional_resource_keys=frozenset({"cancel_dispatch", "cancel_before_dispatch"}),
            public_ports=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.cancel",
                            "orders.submit_group_leg",
                            "orders.resolve_group_leg",
                            "orders.cancel_group_leg",
                        }
                    ),
                    "service.order_query": frozenset(
                        {
                            "orders.query",
                            "orders.query_group_leg",
                            "orders.query_group_cancel",
                        }
                    ),
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.cancel",
                            "orders.submit_group_leg",
                            "orders.resolve_group_leg",
                            "orders.cancel_group_leg",
                        }
                    )
                }
            ),
            validator_module_name="bt_api_py.service_execution_account_group_owner",
        ),
        ("execution", "group_coordinator"): _Builtin(
            module_name="bt_api_py.service_execution_group",
            operations_attribute=("GROUP_COORDINATOR_OPERATIONS",),
            resource_keys=frozenset({"store", "targets", "run_bindings"}),
            public_ports=MappingProxyType(
                {
                    "service.order_group_entry": frozenset(
                        {
                            "groups.submit",
                            "groups.query",
                            "groups.cancel",
                            "groups.roll_exit",
                            "groups.query_roll_exit",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.order_group_entry": frozenset(
                        {"groups.submit", "groups.cancel", "groups.roll_exit"}
                    )
                }
            ),
        ),
        ("execution", "legacy_import_owner"): _Builtin(
            module_name="bt_api_execution.service_paper_legacy_import",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"store", "targets", "legacy_import_domain"}),
            public_ports=MappingProxyType(
                {
                    "service.paper_legacy_import": frozenset(
                        {
                            "paper.import.status",
                            "paper.import.inspect_source",
                            "paper.import.prepare",
                            "paper.import.activate",
                            "paper.import.abort",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.paper_legacy_import": frozenset(
                        {
                            "paper.import.prepare",
                            "paper.import.activate",
                            "paper.import.abort",
                        }
                    )
                }
            ),
        ),
        ("risk", "group_reservations"): _Builtin(
            module_name="bt_api_py.service_group_reservations",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"accepted_group_store", "group_runtime_bundle"}),
            public_ports=MappingProxyType(
                {
                    "service.group_reservations": frozenset(
                        {
                            "reservations.reserve",
                            "reservations.query",
                            "reservations.release",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.group_reservations": frozenset(
                        {"reservations.reserve", "reservations.release"}
                    )
                }
            ),
        ),
        ("risk", "policy_catalog"): _Builtin(
            module_name="bt_api_risk.service_component",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"catalog"}),
            optional_resource_keys=frozenset({"confirmed_policy_store"}),
            public_ports=MappingProxyType(
                {
                    "service.risk_policy": frozenset(
                        {
                            "policy.read",
                            "policy.draft",
                            "policy.approve",
                            "policy.publish",
                            "policy.receipt",
                            "policy.inspect",
                            "policy.confirmation.read",
                            "policy.budget.propose",
                            "policy.budget.approve",
                            "policy.budget.publish_member",
                            "policy.budget.confirm_member",
                            "policy.budget.owner_confirm_member",
                            "policy.budget.reject_member",
                            "policy.budget.mark_unknown",
                            "policy.budget.retract",
                            "policy.budget.read",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.risk_policy": frozenset(
                        {
                            "policy.draft", "policy.approve", "policy.publish",
                            "policy.budget.propose", "policy.budget.approve",
                            "policy.budget.publish_member", "policy.budget.confirm_member",
                            "policy.budget.owner_confirm_member",
                            "policy.budget.reject_member", "policy.budget.mark_unknown",
                            "policy.budget.retract",
                        }
                    )
                }
            ),
        ),
        ("risk", "portfolio_analytics"): _Builtin(
            module_name="bt_api_risk.service_analytics",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset({"analysis"}),
            public_ports=MappingProxyType(
                {
                    "service.risk_analysis": frozenset(
                        {
                            "analysis.submit",
                            "analysis.query",
                            "analysis.cancel",
                            "analysis.input_upload",
                        }
                    )
                }
            ),
            internal_ports=frozenset(),
            write_operations_by_port=MappingProxyType(
                {
                    "service.risk_analysis": frozenset(
                        {"analysis.submit", "analysis.cancel", "analysis.input_upload"}
                    )
                }
            ),
            validator_module_name="bt_api_risk.service_component",
        ),
        ("risk", "group_policy"): _Builtin(
            module_name="bt_api_risk.service_component",
            operations_attribute=("GroupPolicyService", "SUPPORTED_OPERATIONS"),
            resource_keys=frozenset(),
            public_ports=MappingProxyType({}),
            internal_ports=frozenset({"service.group_admission"}),
        ),
        ("risk", "account_owner"): _Builtin(
            module_name="bt_api_py.service_risk_order_entry",
            operations_attribute=("SUPPORTED_OPERATIONS",),
            resource_keys=frozenset(
                {"bt_api", "targets", "admission", "journal", "gate", "provider_contracts"}
            ),
            optional_resource_keys=frozenset(
                {
                    "resolved_budget_admission",
                    "account_policy_admission_resolver",
                    "account_policy_scope",
                    "group_compensation_authorization_source",
                    "group_roll_exit_authorization_source",
                    "position_valuation_resolver",
                    "dispatch_quota_admission",
                }
            ),
            public_ports=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.submit_group_compensation_close",
                            "orders.submit_group_roll_exit",
                        }
                    ),
                    "service.order_query": frozenset(
                        {
                            "orders.query",
                            "orders.prepare_group_compensation_close",
                            "orders.query_group_compensation_close",
                            "orders.prepare_group_roll_exit",
                            "orders.query_group_roll_exit",
                        }
                    ),
                }
            ),
            internal_ports=frozenset({"service.provider_session"}),
            validator_module_name="bt_api_py.service_risk_position_snapshot",
            write_operations_by_port=MappingProxyType(
                {
                    "service.order_entry": frozenset(
                        {
                            "orders.submit",
                            "orders.submit_group_compensation_close",
                            "orders.submit_group_roll_exit",
                        }
                    )
                }
            ),
        ),
    }
)


_ADMISSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "order_gate",
        "cancel_gate",
        "basic_admission_gate",
        "allow_unprotected",
        "cancel_quota_admission",
    }
)
_ACCOUNT_OWNER_ADMISSION_KEYS: Final[frozenset[str]] = _ADMISSION_KEYS | frozenset(
    {
        "position_baseline_authorizer",
        "recovery_close_authorizer",
    }
)
_GROUP_COMPENSATION_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "orders.prepare_group_compensation_close",
        "orders.submit_group_compensation_close",
        "orders.query_group_compensation_close",
    }
)
_GROUP_COMPENSATION_SUBMIT: Final[str] = "orders.submit_group_compensation_close"
_GROUP_ROLL_EXIT_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "orders.prepare_group_roll_exit",
        "orders.submit_group_roll_exit",
        "orders.query_group_roll_exit",
    }
)
_GROUP_ROLL_EXIT_SUBMIT: Final[str] = "orders.submit_group_roll_exit"

_EXECUTION_OWNER_LOCK_GUARD = threading.Lock()
_EXECUTION_OWNER_LOCK_PATHS: set[str] = set()
_EXECUTION_OWNER_LOCK_FILES: dict[str, Any] = {}
_EXECUTION_OWNER_MEMORY_STORES: dict[int, object] = {}


def _forget_execution_owner_path(key: str, owner_file: Any) -> None:
    if not owner_file.closed:
        return
    with _EXECUTION_OWNER_LOCK_GUARD:
        if _EXECUTION_OWNER_LOCK_FILES.get(key) is owner_file:
            _EXECUTION_OWNER_LOCK_FILES.pop(key, None)
        if key not in _EXECUTION_OWNER_LOCK_FILES:
            _EXECUTION_OWNER_LOCK_PATHS.discard(key)


class _ExecutionOwnerFileLock:
    """Retain advisory ownership of one resolved execution-store pathname."""

    def __init__(self, owner_file: Any, key: str) -> None:
        self._owner_file = owner_file
        self._key = key

    def close(self) -> None:
        owner_file = self._owner_file
        if owner_file is None:
            return
        try:
            # Closing the still-locked descriptor releases the OS lock. Do not
            # explicitly unlock first: if close then fails, another process
            # must not enter while this owner still has an open descriptor.
            owner_file.close()
        except BaseException:
            if owner_file.closed:
                self._owner_file = None
            _forget_execution_owner_path(self._key, owner_file)
            raise
        if not owner_file.closed:
            raise ServiceComponentError("ORDER_OWNER_LOCK_RELEASE_FAILED")
        self._owner_file = None
        _forget_execution_owner_path(self._key, owner_file)


class _ExecutionOwnerMemoryLock:
    """Exclude another local owner reusing the same in-memory store object."""

    def __init__(self, store: object) -> None:
        self._store: object | None = store

    def close(self) -> None:
        store = self._store
        if store is None:
            return
        key = id(store)
        with _EXECUTION_OWNER_LOCK_GUARD:
            if _EXECUTION_OWNER_MEMORY_STORES.get(key) is store:
                _EXECUTION_OWNER_MEMORY_STORES.pop(key, None)
        self._store = None


def _acquire_execution_owner_lock(
    store: object,
) -> _ExecutionOwnerFileLock | _ExecutionOwnerMemoryLock:
    """Lock the resolved database pathname, or object identity for memory stores.

    The sidecar protocol is advisory and pathname-based. Symlink aliases resolve
    to one key; hard links and replacement or unlinking of the sidecar are
    outside its exclusion guarantee.
    """

    raw_path = getattr(store, "path", None)
    if isinstance(raw_path, os.PathLike):
        try:
            raw_path = os.fspath(raw_path)
        except (TypeError, ValueError):
            raise ServiceComponentError("ORDER_OWNER_LOCK_UNAVAILABLE") from None
    if type(raw_path) is not str or not raw_path:
        raise ServiceComponentError("ORDER_OWNER_LOCK_UNAVAILABLE")
    if raw_path == ":memory:":
        memory_lock = _ExecutionOwnerMemoryLock(store)
        key = id(store)
        with _EXECUTION_OWNER_LOCK_GUARD:
            if key in _EXECUTION_OWNER_MEMORY_STORES:
                raise ServiceComponentError("ORDER_OWNER_ALREADY_ACTIVE")
            _EXECUTION_OWNER_MEMORY_STORES[key] = store
        return memory_lock
    try:
        key = os.path.normcase(str(Path(raw_path).expanduser().resolve(strict=True)))
    except (OSError, RuntimeError, ValueError):
        raise ServiceComponentError("ORDER_OWNER_LOCK_UNAVAILABLE") from None

    with _EXECUTION_OWNER_LOCK_GUARD:
        if key in _EXECUTION_OWNER_LOCK_PATHS:
            raise ServiceComponentError("ORDER_OWNER_ALREADY_ACTIVE")
        _EXECUTION_OWNER_LOCK_PATHS.add(key)

    owner_file = None
    try:
        # Match ServiceRegistry's portable lifetime-lock protocol while using
        # the resolved database pathname, independent of registry_path.
        # This sidecar does not coordinate hard-link aliases or a sidecar
        # replaced or unlinked by another process with directory write access.
        owner_file = open(key + ".service_execution_owner.lock", "a+b")  # noqa: SIM115
        with _EXECUTION_OWNER_LOCK_GUARD:
            _EXECUTION_OWNER_LOCK_FILES[key] = owner_file
        owner_file.seek(0, os.SEEK_END)
        if owner_file.tell() == 0:
            owner_file.write(b"\0")
            owner_file.flush()
        owner_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(owner_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(owner_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _ExecutionOwnerFileLock(owner_file, key)
    except BaseException as error:
        if owner_file is not None:
            try:
                owner_file.close()
            except BaseException:
                # Keep both the in-process claim and descriptor reference until
                # a retry confirms that close actually completed.
                _forget_execution_owner_path(key, owner_file)
                raise ServiceComponentError("ORDER_OWNER_LOCK_RELEASE_FAILED") from None
            _forget_execution_owner_path(key, owner_file)
        else:
            with _EXECUTION_OWNER_LOCK_GUARD:
                _EXECUTION_OWNER_LOCK_PATHS.discard(key)
        if not isinstance(error, Exception):
            raise
        if isinstance(error, OSError) and error.errno in {
            errno.EACCES,
            errno.EAGAIN,
            errno.EDEADLK,
        }:
            raise ServiceComponentError("ORDER_OWNER_ALREADY_ACTIVE") from None
        raise ServiceComponentError("ORDER_OWNER_LOCK_UNAVAILABLE") from None


def _resources_with_execution_owner_lock(
    resources: ComponentResources,
    owner_lock: _ExecutionOwnerFileLock | _ExecutionOwnerMemoryLock | None,
    *,
    before_close: Callable[[], None] | None = None,
) -> ComponentResources:
    if owner_lock is None and before_close is None:
        return resources

    def close_owned_resources() -> None:
        # Release the writer exclusion only after trusted provider cleanup has
        # completed. If cleanup fails, a later host retry still owns the lock.
        if before_close is not None:
            before_close()
        resources.close()
        if owner_lock is not None:
            owner_lock.close()

    return ComponentResources.owned(
        resources.values,
        ready=resources.ready,
        close=close_owned_resources,
        internal_ports=resources.internal_ports,
        operation_readiness=resources.operation_readiness,
        maintain=resources.maintain,
        next_maintenance_delay=resources.next_maintenance_delay,
    )


def _builtin_for_spec(spec: ComponentSpec) -> _Builtin | None:
    role = spec.options.get("role")
    if type(role) is str:
        role_builtin = _ROLE_BUILTINS.get((spec.component, role))
        if role_builtin is not None:
            return role_builtin
    return _BUILTINS.get(spec.component)


def component_specs(components: Mapping[str, Any]) -> tuple[ComponentSpec, ...]:
    """Snapshot normalized component selections from a parsed service config."""

    if not isinstance(components, Mapping) or not components:
        raise ServiceComponentError("EMPTY_COMPONENTS")
    specs: list[ComponentSpec] = []
    seen_instances: set[str] = set()
    for component, raw in components.items():
        if type(component) is not str or not isinstance(raw, Mapping):
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        settings = raw.get("settings")
        if not isinstance(settings, Mapping):
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        instance_id = settings.get("instance_id")
        bind_ports = settings.get("bind_ports")
        options = settings.get("options", {})
        if (
            type(instance_id) is not str
            or type(bind_ports) not in (tuple, list)
            or not isinstance(options, Mapping)
        ):
            raise ServiceComponentError("INVALID_COMPONENT_SPEC")
        if instance_id in seen_instances:
            raise ServiceComponentError("DUPLICATE_COMPONENT_INSTANCE")
        seen_instances.add(instance_id)
        specs.append(
            ComponentSpec(
                component=component,
                instance_id=instance_id,
                bind_ports=tuple(bind_ports),
                options=options,
            )
        )
    return tuple(specs)


def validate_components(specs: Sequence[ComponentSpec]) -> tuple[PreparedComponent, ...]:
    """Validate every selected built-in before any resource provider call."""

    if type(specs) not in (tuple, list) or not specs:
        raise ServiceComponentError("EMPTY_COMPONENTS")
    prepared: list[PreparedComponent] = []
    seen_instances: set[str] = set()
    for spec in specs:
        if type(spec) is not ComponentSpec:
            raise ServiceComponentError("UNKNOWN_COMPONENT")
        if spec.instance_id in seen_instances:
            raise ServiceComponentError("DUPLICATE_COMPONENT_INSTANCE")
        seen_instances.add(spec.instance_id)
        builtin = _builtin_for_spec(spec)
        if builtin is None:
            raise ServiceComponentError("UNKNOWN_COMPONENT")
        try:
            module = importlib.import_module(builtin.module_name)
        except Exception:
            raise ServiceComponentError("BUILTIN_COMPONENT_UNAVAILABLE") from None
        validator_module = module
        if builtin.validator_module_name is not None:
            try:
                validator_module = importlib.import_module(builtin.validator_module_name)
            except Exception:
                raise ServiceComponentError("BUILTIN_COMPONENT_UNAVAILABLE") from None
        validator = getattr(validator_module, "validate_service_options", None)
        if not callable(validator):
            raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
        try:
            normalized = validator(spec.options, spec.bind_ports)
        except Exception:
            raise ServiceComponentError("COMPONENT_OPTIONS_INVALID") from None
        if not isinstance(normalized, Mapping):
            raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")

        operations: object = module
        for attribute in builtin.operations_attribute:
            operations = getattr(operations, attribute, None)
        if type(operations) is not frozenset or any(type(item) is not str for item in operations):
            raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
        if spec.component == "gateway" and spec.options.get("role") not in {
            "account_session_worker", "trading_owner"
        }:
            operations = operations - {"account.snapshot.typed"}
        if spec.component == "gateway" and spec.options.get("role") == "trading_owner":
            if normalized.get("dispatch_enabled") is not True:
                operations = operations - {"direct.dispatch"}
        if spec.component == "gateway" and normalized.get("reconciliation_cut") is True:
            # Only an explicitly enabled worker with a trusted inspector port
            # serves reconciliation evidence (iteration 60, acceptance G2).
            operations = operations | {"account.reconciliation_cut"}
        if spec.component == "gateway" and spec.options.get("role") == "market_hub":
            bounded_operation = getattr(module, "MARKET_READ_AFTER_BOUNDED_OPERATION", None)
            if type(bounded_operation) is not str or bounded_operation not in operations:
                raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
            if normalized.get("bounded_read_after", False) is not True:
                operations = operations - {bounded_operation}

        by_port: dict[str, frozenset[str]] = {}
        write_by_port: dict[str, frozenset[str]] = {}
        for port in spec.bind_ports:
            allowed = builtin.public_ports.get(port)
            if allowed is not None:
                supported = frozenset(allowed.intersection(operations))
                if not supported:
                    raise ServiceComponentError("PUBLIC_PORT_HAS_NO_SUPPORTED_OPERATIONS")
                write_operations = builtin.write_operations_by_port.get(port, frozenset())
                if spec.component == "gateway" and spec.options.get("role") == "trading_owner":
                    write_operations = write_operations.intersection(supported)
                if type(write_operations) is not frozenset or not write_operations.issubset(
                    supported
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                by_port[port] = supported
                write_by_port[port] = write_operations
            elif port in builtin.internal_ports:
                continue
            else:
                raise ServiceComponentError("UNSUPPORTED_PUBLIC_PORT")
        prepared.append(
            PreparedComponent(
                spec=spec,
                options=MappingProxyType(dict(normalized)),
                module=module,
                operations_by_port=MappingProxyType(by_port),
                write_operations_by_port=MappingProxyType(write_by_port),
            )
        )
    return tuple(prepared)


def order_components(prepared: Sequence[PreparedComponent]) -> tuple[PreparedComponent, ...]:
    """Order the fixed same-service provider-session dependency first."""

    if type(prepared) not in (tuple, list) or not prepared:
        raise ServiceComponentError("EMPTY_COMPONENTS")
    by_instance = {item.spec.instance_id: item for item in prepared}
    if len(by_instance) != len(prepared):
        raise ServiceComponentError("DUPLICATE_COMPONENT_INSTANCE")
    dependencies: dict[str, set[str]] = {instance: set() for instance in by_instance}
    for item in prepared:
        if item.spec.component not in {"execution", "risk"} or (
            item.spec.component == "risk"
            and item.spec.options.get("role") != "account_owner"
        ):
            continue
        dependency = item.options.get("provider_session_ref")
        if dependency is None:
            continue
        target = by_instance.get(dependency)
        if (
            target is None
            or target.spec.component != "gateway"
            or target.spec.options.get("role") != "account_session_worker"
        ):
            raise ServiceComponentError("PROVIDER_SESSION_REFERENCE_INVALID")
        dependencies[item.spec.instance_id].add(dependency)

    ordered: list[PreparedComponent] = []
    remaining = set(by_instance)
    while remaining:
        ready = sorted(
            instance for instance in remaining if not dependencies[instance].intersection(remaining)
        )
        if not ready:
            raise ServiceComponentError("COMPONENT_DEPENDENCY_CYCLE")
        for instance in ready:
            ordered.append(by_instance[instance])
            remaining.remove(instance)
    return tuple(ordered)


def _group_runtime_bundle(value: object) -> object:
    """Validate the provider-owned, group-only Risk/Execution composition."""

    try:
        module = importlib.import_module("bt_api_py.service_execution_group_proofs")
    except Exception:
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_UNAVAILABLE") from None
    bundle_type = getattr(module, "GroupProofRuntimeBundle", None)
    if not isinstance(bundle_type, type) or type(value) is not bundle_type:
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID")
    try:
        risk_admission = value.risk_admission  # type: ignore[attr-defined]
        account_scoped_admission = value.account_scoped_admission  # type: ignore[attr-defined]
        proof_source = value.proof_source  # type: ignore[attr-defined]
        reservation_targets = value.reservation_targets  # type: ignore[attr-defined]
        proof_targets = value.proof_targets  # type: ignore[attr-defined]
        reservation_target_for = value.reservation_target_for  # type: ignore[attr-defined]
        proof_target_for = value.proof_target_for  # type: ignore[attr-defined]
        execution_scope_for = value.execution_scope_for  # type: ignore[attr-defined]
        require_runtime_bundle = value.require_runtime_bundle  # type: ignore[attr-defined]
    except Exception:
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID") from None
    if (
        type(risk_admission) is not getattr(module, "DurableRiskAdmissionAdapter", None)
        or type(account_scoped_admission)
        is not getattr(module, "AccountScopedGroupAdmissionAdapter", None)
        or type(proof_source) is not getattr(module, "GroupProofSource", None)
        or type(reservation_targets) is not MappingProxyType
        or type(proof_targets) is not MappingProxyType
        or not reservation_targets
        or set(reservation_targets) != set(proof_targets)
        or not callable(reservation_target_for)
        or not callable(proof_target_for)
        or not callable(execution_scope_for)
        or not callable(require_runtime_bundle)
    ):
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID")
    target_for_template = getattr(proof_source, "target_for_template", None)
    reservation_target_type = getattr(module, "GroupReservationTarget", None)
    execution_scope_type = getattr(module, "ExecutionScope", None)
    account_scope_type = getattr(module, "AccountScope", None)
    risk_scope_fingerprint = getattr(module, "risk_account_scope_fingerprint", None)
    if (
        not callable(target_for_template)
        or not isinstance(reservation_target_type, type)
        or not isinstance(execution_scope_type, type)
        or not isinstance(account_scope_type, type)
        or not callable(risk_scope_fingerprint)
    ):
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID")
    try:
        require_runtime_bundle(
            account_scoped_admission=account_scoped_admission,
            risk_admission=risk_admission,
        )
        account_scoped_admission.require_admission_gate(risk_admission)
        for wire_scope in reservation_targets:
            if (
                type(wire_scope) is not WireScope
                or wire_scope.group_id is not None
                or wire_scope.leg_id is not None
            ):
                raise TypeError("invalid group scope key")
            reservation_target = reservation_targets[wire_scope]
            if (
                type(reservation_target) is not reservation_target_type
                or reservation_target_for(wire_scope) is not reservation_target
                or reservation_target.admission is not risk_admission
                or type(reservation_target.account_scope) is not account_scope_type
                or account_scoped_admission.risk_scope_fingerprint
                != risk_scope_fingerprint(reservation_target.account_scope.key)
            ):
                raise TypeError("reservation target lookup changed identity")
            proof_target = proof_targets[wire_scope]
            if type(proof_target) is not getattr(module, "GroupProofTarget", None):
                raise TypeError("invalid group proof target")
            execution_scope = proof_target.execution_scope
            if (
                type(execution_scope) is not execution_scope_type
                or proof_target.account_scope != reservation_target.account_scope
                or execution_scope.account_ref != wire_scope.account_ref
                or execution_scope.strategy_id != wire_scope.strategy_ref
            ):
                raise TypeError("group proof target scope binding changed")
            # Bundle keys are stable account templates. The public
            # proof_target_for()/execution_scope_for() methods resolve a
            # per-leg child scope and correctly reject this key shape.
            if target_for_template(wire_scope) is not proof_target:
                raise TypeError("proof target template lookup changed identity")
    except Exception:
        raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID") from None
    return value


def _account_risk_policy_metadata(
    resources: ComponentResources,
    *,
    spec: ComponentSpec,
    options: Mapping[str, object],
    module: object,
) -> tuple[tuple[AccountRiskPolicyBinding, ...], frozenset[str]]:
    """Bind an account-order route to the actual configured Risk policy.

    A configured account policy reference may be an operator alias. Aliases
    need an explicit resource-provider binding to the exact policy object on
    the gate; the policy fingerprint is always read from that object. A
    confirmed account-policy resolver, when supplied by the trusted resource
    provider, is re-read and rebound here before the order route is exposed.
    """

    risk_owner = spec.component == "risk" and options.get("role") == "account_owner"
    if not risk_owner or "service.order_entry" not in spec.bind_ports:
        if resources.risk_policy_bindings or any(
            key in resources.values
            for key in (
                "account_policy_admission_resolver",
                "account_policy_scope",
            )
        ):
            raise ServiceComponentError("UNEXPECTED_RISK_POLICY_BINDING")
        return (), frozenset()

    try:
        risk_module = importlib.import_module("bt_api_risk")
        gate_type = getattr(risk_module, "DurableRiskGate", None)
        policy_type = getattr(risk_module, "RiskPolicy", None)
        account_scope_type = getattr(risk_module, "AccountScope", None)
        target_type = getattr(module, "RiskOrderTarget", None)
        gate = resources.values["gate"]
        targets = resources.values["targets"]
        policy = gate.policy
        configured_ref = options["account_policy_ref"]
        policy_id = policy.policy_id
        fingerprint = policy.fingerprint
    except Exception:
        raise ServiceComponentError("RISK_POLICY_BINDING_UNAVAILABLE") from None

    if (
        not isinstance(gate_type, type)
        or type(gate) is not gate_type
        or not isinstance(policy_type, type)
        or type(policy) is not policy_type
        or not isinstance(account_scope_type, type)
        or not isinstance(target_type, type)
        or type(configured_ref) is not str
        or not configured_ref
        or type(policy_id) is not str
        or not policy_id
        or type(fingerprint) is not str
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
        or not isinstance(targets, Mapping)
        or not targets
    ):
        raise ServiceComponentError("RISK_POLICY_BINDING_INVALID")

    resolved_budget = resources.values.get("resolved_budget_admission")
    has_account_policy_resolver = "account_policy_admission_resolver" in resources.values
    has_account_policy_scope = "account_policy_scope" in resources.values
    account_policy_resolver = resources.values.get("account_policy_admission_resolver")
    account_policy_scope = resources.values.get("account_policy_scope")
    if has_account_policy_resolver != has_account_policy_scope:
        raise ServiceComponentError("ACCOUNT_POLICY_RESOLUTION_INVALID")
    if resolved_budget is not None and has_account_policy_resolver:
        raise ServiceComponentError("ACCOUNT_POLICY_MODE_CONFLICT")
    if has_account_policy_resolver:
        try:
            admission_module = importlib.import_module("bt_api_risk.policy_admission")
            resolver_type = getattr(
                admission_module, "PolicyCatalogAccountAdmissionResolver", None
            )
            resolution_error_type = getattr(
                admission_module, "PolicyAdmissionResolutionError", None
            )
            resolved_type = getattr(admission_module, "ResolvedAccountPolicy", None)
            bound_type = getattr(admission_module, "BoundAccountPolicy", None)
            binding_type = getattr(risk_module, "DurableRiskPolicyBinding", None)
        except Exception:
            raise ServiceComponentError("ACCOUNT_POLICY_RESOLUTION_UNAVAILABLE") from None
        if (
            not isinstance(resolver_type, type)
            or not isinstance(resolution_error_type, type)
            or type(account_policy_resolver) is not resolver_type
            or type(account_policy_scope) is not WireScope
            or not isinstance(resolved_type, type)
            or not isinstance(bound_type, type)
            or not isinstance(binding_type, type)
            or account_policy_scope.account_ref is None
            or account_policy_scope.account_refs
            or account_policy_scope.strategy_ref is not None
            or account_policy_scope.run_id is not None
            or account_policy_scope.group_id is not None
            or account_policy_scope.leg_id is not None
        ):
            raise ServiceComponentError("ACCOUNT_POLICY_RESOLUTION_INVALID")
    if resolved_budget is not None:
        try:
            budget_module = importlib.import_module("bt_api_risk.budget_admission")
            resolved_type = getattr(budget_module, "ResolvedBudgetAdmission", None)
            resolved_policy = resolved_budget.risk_policy
            resolved_account = resolved_budget.account_ref
            resolved_portfolio = resolved_budget.portfolio_ref
            generation_ref = resolved_budget.generation_ref
            policy_version = resolved_budget.policy_version
        except Exception:
            raise ServiceComponentError("BUDGET_POLICY_RESOLUTION_INVALID") from None
        if (
            not isinstance(resolved_type, type)
            or type(resolved_budget) is not resolved_type
            or type(resolved_policy) is not policy_type
            or policy is not resolved_policy
            or type(resolved_account) is not str
            or not resolved_account
            or type(resolved_portfolio) is not str
            or not resolved_portfolio
            or type(generation_ref) is not str
            or not generation_ref
            or type(policy_version) is not str
            or len(policy_version) != 64
            or any(character not in "0123456789abcdef" for character in policy_version)
            or configured_ref != resolved_budget.policy_ref
            or configured_ref != policy_id
        ):
            raise ServiceComponentError("BUDGET_POLICY_RESOLUTION_MISMATCH")

    target_scopes: set[WireScope] = set()
    target_account_scopes: set[object] = set()
    manual_budget_scope = resolved_budget is not None
    manual_account_policy_scope = has_account_policy_resolver
    for wire_scope, target in targets.items():
        try:
            account_scope = target.account_scope
            strategy_id = target.strategy_id
            provider_account_id = target.provider_account_id
        except Exception:
            raise ServiceComponentError("RISK_POLICY_BINDING_INVALID") from None
        if (
            type(wire_scope) is not WireScope
            or type(target) is not target_type
            or type(account_scope) is not account_scope_type
            or type(provider_account_id) is not str
            or account_scope.account_id != provider_account_id
            or wire_scope in target_scopes
            or not wire_scope.account_ref
            or wire_scope.account_refs
            or (
                wire_scope.strategy_ref != strategy_id
                and not (
                    (manual_budget_scope or manual_account_policy_scope)
                    and wire_scope.strategy_ref is None
                    and wire_scope.manual_book_ref is not None
                )
            )
            or wire_scope.run_id is not None
            or wire_scope.group_id is not None
            or wire_scope.leg_id is not None
            or (
                wire_scope.manual_book_ref is not None
                and (
                    not (manual_budget_scope or manual_account_policy_scope)
                    or wire_scope.strategy_ref is not None
                    or wire_scope.portfolio_ref is not None
                )
            )
            or (
                manual_budget_scope
                and (
                    wire_scope.strategy_ref is not None
                    or wire_scope.manual_book_ref is None
                    or wire_scope.portfolio_ref is not None
                )
            )
        ):
            raise ServiceComponentError("RISK_POLICY_BINDING_INVALID")
        target_scopes.add(wire_scope)
        target_account_scopes.add(account_scope)
        if resolved_budget is not None and wire_scope.account_ref != resolved_budget.account_ref:
            raise ServiceComponentError("BUDGET_POLICY_SCOPE_MISMATCH")

    if (
        has_account_policy_resolver
        and account_policy_scope.manual_book_ref is not None
        and target_scopes != {account_policy_scope}
    ):
        raise ServiceComponentError("ACCOUNT_POLICY_SCOPE_MISMATCH")

    if has_account_policy_resolver:
        try:
            account_refs = {wire_scope.account_ref for wire_scope in target_scopes}
            execution_domains = {
                wire_scope.execution_domain_ref for wire_scope in target_scopes
            }
            if (
                len(account_refs) != 1
                or account_policy_scope.account_ref not in account_refs
                or len(execution_domains) != 1
                or account_policy_scope.execution_domain_ref != next(iter(execution_domains))
                or len(target_account_scopes) != 1
                or (
                    account_policy_scope.portfolio_ref is not None
                    and any(
                        wire_scope.portfolio_ref != account_policy_scope.portfolio_ref
                        for wire_scope in target_scopes
                    )
                )
            ):
                raise TypeError("account policy scope does not select this owner")
            account_ref = next(iter(account_refs))
            account_scope = next(iter(target_account_scopes))
            try:
                bound_policy = account_policy_resolver.resolve_confirmed_and_bind(
                    configured_ref,
                    account_ref,
                    scope=account_policy_scope,
                    account_scope=account_scope,
                    gate=gate,
                )
            except resolution_error_type as error:
                if error.code != "POLICY_NOT_CONFIRMED":
                    raise
                # First activation is permitted only from an exact published
                # document and only after the same account gate has persisted
                # and read back the policy binding. Any other failure remains
                # fail-closed; offline restarts never consult catalog/latest.
                published = account_policy_resolver.resolve_published(
                    configured_ref,
                    account_ref,
                    scope=account_policy_scope,
                )
                if (
                    type(published) is not resolved_type
                    or published.policy_ref != configured_ref
                    or published.account_ref != account_ref
                    or type(published.owner_principal) is not str
                    or not published.owner_principal
                ):
                    raise TypeError("published policy identity is invalid")
                bound_policy = account_policy_resolver.confirm_after_gate_binding(
                    configured_ref,
                    account_ref,
                    principal_ref=published.owner_principal,
                    scope=account_policy_scope,
                    account_scope=account_scope,
                    gate=gate,
                )
            resolved = bound_policy.resolved
            persisted_binding = bound_policy.binding
            if (
                type(bound_policy) is not bound_type
                or type(resolved) is not resolved_type
                or type(persisted_binding) is not binding_type
                or type(resolved.policy_ref) is not str
                or resolved.policy_ref != configured_ref
                or type(resolved.policy_version) is not str
                or resolved.policy_version != resolved.policy_version.lower()
                or len(resolved.policy_version) != 64
                or any(character not in "0123456789abcdef" for character in resolved.policy_version)
                or type(resolved.account_ref) is not str
                or resolved.account_ref != account_ref
                or type(resolved.owner_principal) is not str
                or not resolved.owner_principal
                or type(resolved.confirmed_utc) is not str
                or not resolved.confirmed_utc
                or type(resolved.risk_policy) is not policy_type
                or resolved.risk_policy.policy_id != policy_id
                or resolved.risk_policy.fingerprint != fingerprint
                or persisted_binding.scope != account_scope
                or persisted_binding.policy_id != configured_ref
                or persisted_binding.policy_fingerprint != fingerprint
                or persisted_binding.ledger_identity_ref != gate.ledger_identity_ref
            ):
                raise TypeError("confirmed policy did not bind to the owner gate")

            admission = resources.values["admission"]
            adapter_type = getattr(risk_module, "DurableRiskAdmissionAdapter", None)
            if not isinstance(admission, Mapping) or set(admission) != target_scopes:
                raise TypeError("invalid account admission map")
            for wire_scope, adapter in admission.items():
                if (
                    not isinstance(adapter_type, type)
                    or type(adapter) is not adapter_type
                    or adapter.is_bound_to(gate) is not True
                ):
                    raise TypeError("account admission does not use the owner gate")
                adapter_binding = adapter.policy_binding
                if (
                    adapter_binding.policy_id != configured_ref
                    or adapter_binding.policy_fingerprint != fingerprint
                ):
                    raise TypeError("account admission policy differs from confirmation")
            current_binding = gate.bind_policy(account_scope)
            if (
                current_binding.scope != account_scope
                or current_binding.policy_id != configured_ref
                or current_binding.policy_fingerprint != fingerprint
                or current_binding.ledger_identity_ref != gate.ledger_identity_ref
            ):
                raise TypeError("current Risk ledger binding changed")
        except ServiceComponentError:
            raise
        except Exception:
            raise ServiceComponentError("ACCOUNT_POLICY_NOT_EFFECTIVE") from None

    if resolved_budget is not None:
        if len(target_account_scopes) != 1:
            raise ServiceComponentError("BUDGET_POLICY_SCOPE_MISMATCH")
        try:
            admission = resources.values["admission"]
            adapter_type = getattr(risk_module, "DurableRiskAdmissionAdapter", None)
            if not isinstance(admission, Mapping) or set(admission) != target_scopes:
                raise TypeError("invalid account admission map")
            for _wire_scope, adapter in admission.items():
                if (
                    not isinstance(adapter_type, type)
                    or type(adapter) is not adapter_type
                    or adapter.is_bound_to(gate) is not True
                ):
                    raise TypeError("account admission does not use the owner gate")
                binding = adapter.policy_binding
                if (
                    binding.policy_id != configured_ref
                    or binding.policy_fingerprint != fingerprint
                ):
                    raise TypeError("account admission policy differs from the catalog")
            account_scope = next(iter(target_account_scopes))
            persisted_binding = gate.bind_policy(account_scope)
            if (
                persisted_binding.scope != account_scope
                or persisted_binding.policy_id != configured_ref
                or persisted_binding.policy_fingerprint != fingerprint
                or persisted_binding.ledger_identity_ref != gate.ledger_identity_ref
            ):
                raise TypeError("durable account policy binding differs from the catalog")
        except ServiceComponentError:
            raise
        except Exception:
            # The host must fail startup if confirmation, the old ledger
            # binding, or the actual account adapter cannot prove this exact
            # generation. Existing reservations and UNKNOWN rows stay intact.
            raise ServiceComponentError("BUDGET_POLICY_NOT_EFFECTIVE") from None

    supplied = resources.risk_policy_bindings
    if configured_ref != policy_id and not supplied:
        raise ServiceComponentError("RISK_POLICY_BINDING_REQUIRED")
    if supplied:
        by_scope: dict[WireScope, TrustedRiskPolicyBinding] = {}
        for binding in supplied:
            if (
                type(binding) is not TrustedRiskPolicyBinding
                or binding.reference != configured_ref
                or binding.policy is not policy
                or binding.scope not in target_scopes
                or binding.scope in by_scope
            ):
                raise ServiceComponentError("RISK_POLICY_BINDING_MISMATCH")
            by_scope[binding.scope] = binding
        if set(by_scope) != target_scopes:
            raise ServiceComponentError("RISK_POLICY_BINDING_MISMATCH")
    elif configured_ref != policy_id:
        raise ServiceComponentError("RISK_POLICY_BINDING_REQUIRED")

    return (
        tuple(
            AccountRiskPolicyBinding(spec.instance_id, target_scope, configured_ref, fingerprint)
            for target_scope in sorted(
                target_scopes,
                key=lambda scope: (
                    scope.execution_domain_ref,
                    scope.account_ref or "",
                    scope.strategy_ref or "",
                ),
            )
        ),
        frozenset({"service.order_entry"}),
    )


def build_component(
    prepared: PreparedComponent,
    *,
    scope: WireScope,
    resource_provider: ServiceResourceProvider,
    on_resources: Callable[[ComponentResources], None] | None = None,
    borrowed_upstream: BorrowedServiceClient | None = None,
    service_identity: WireIdentity | None = None,
    trusted_group_write_policies: tuple[TrustedGroupWritePolicy, ...] = (),
    trusted_group_reservation_policies: tuple[TrustedGroupReservationPolicy, ...] = (),
    trusted_group_resolution_policies: tuple[TrustedGroupResolutionPolicy, ...] = (),
    trusted_internal_ports: Mapping[str, object] | None = None,
) -> ServiceComponent:
    """Resolve trusted resources and construct one fixed adapter."""

    if type(prepared) is not PreparedComponent or type(scope) is not WireScope:
        raise ServiceComponentError("INVALID_COMPONENT_BUILD")
    if not callable(resource_provider):
        raise ServiceComponentError("RESOURCE_PROVIDER_REQUIRED")
    if borrowed_upstream is not None and type(borrowed_upstream) is not BorrowedServiceClient:
        raise ServiceComponentError("INVALID_BORROWED_UPSTREAM")
    if service_identity is not None and type(service_identity) is not WireIdentity:
        raise ServiceComponentError("INVALID_SERVICE_IDENTITY")
    if type(trusted_group_write_policies) is not tuple or any(
        type(policy) is not TrustedGroupWritePolicy for policy in trusted_group_write_policies
    ):
        raise ServiceComponentError("INVALID_GROUP_WRITE_POLICIES")
    if type(trusted_group_reservation_policies) is not tuple or any(
        type(policy) is not TrustedGroupReservationPolicy
        for policy in trusted_group_reservation_policies
    ):
        raise ServiceComponentError("INVALID_GROUP_RESERVATION_POLICIES")
    if type(trusted_group_resolution_policies) is not tuple or any(
        type(policy) is not TrustedGroupResolutionPolicy
        for policy in trusted_group_resolution_policies
    ):
        raise ServiceComponentError("INVALID_GROUP_RESOLUTION_POLICIES")
    if trusted_internal_ports is not None and not isinstance(trusted_internal_ports, Mapping):
        raise ServiceComponentError("INVALID_TRUSTED_INTERNAL_PORTS")
    spec = prepared.spec
    builtin = _builtin_for_spec(spec)
    if builtin is None:
        raise ServiceComponentError("UNKNOWN_COMPONENT")
    resources: ComponentResources | None = None
    tracked_by_caller = False
    execution_owner_lock: _ExecutionOwnerFileLock | _ExecutionOwnerMemoryLock | None = None
    execution_owner_lock_transferred = False
    adapter_close_before_resources: Callable[[], None] | None = None
    defer_resource_tracking = "service.order_entry" in spec.bind_ports and (
        (
            spec.component == "execution"
            and spec.options.get("role")
            in {"account_owner", "group_account_owner", "account_group_owner"}
        )
        or (spec.component == "risk" and spec.options.get("role") == "account_owner")
    )
    try:
        resources = resource_provider(
            spec.component,
            spec.instance_id,
            prepared.options,
            scope,
        )
    except ServiceResourceConstructionError as failure:
        # The provider failed before it could return its completed values.
        # Transfer its cleanup handle before exposing the finite startup error.
        # If handoff or normal cleanup fails, preserve the typed exception so
        # even a direct build caller can still reach the retained resources.
        if on_resources is not None:
            try:
                on_resources(failure.resources)
            except BaseException:
                raise failure from None
        else:
            try:
                failure.resources.close()
            except BaseException:
                raise failure from None
        raise ServiceComponentError("RESOURCE_RESOLUTION_FAILED") from None
    except Exception:
        raise ServiceComponentError("RESOURCE_RESOLUTION_FAILED") from None
    if type(resources) is not ComponentResources:
        raise ServiceComponentError("INVALID_COMPONENT_RESOURCES")
    injected_internal_ports = (
        {} if trusted_internal_ports is None else dict(trusted_internal_ports)
    )
    if injected_internal_ports:
        if (
            spec.component != "risk"
            or spec.options.get("role") != "account_owner"
            or spec.options.get("provider_session_ref") is None
            or "service.provider_session" not in spec.bind_ports
            or set(injected_internal_ports) != {"service.provider_session"}
            or "service.provider_session" in resources.internal_ports
        ):
            if on_resources is not None:
                on_resources(resources)
            else:
                try:
                    resources.close()
                except Exception:
                    pass
            raise ServiceComponentError("TRUSTED_PROVIDER_SESSION_INJECTION_INVALID")
        try:
            worker_module = importlib.import_module("bt_api_gateway.account_session_worker")
            worker_type = getattr(worker_module, "GatewayAccountSessionWorker", None)
            worker = injected_internal_ports["service.provider_session"]
            if not isinstance(worker_type, type) or type(worker) is not worker_type:
                raise TypeError
            merged_internal_ports = dict(resources.internal_ports)
            merged_internal_ports.update(injected_internal_ports)
            if resources.ownership is ResourceOwnership.BORROWED:
                resources = ComponentResources.borrowed(
                    resources.values,
                    ready=resources.ready,
                    internal_ports=merged_internal_ports,
                    risk_policy_bindings=resources.risk_policy_bindings,
                    shared_collateral_domains=resources.shared_collateral_domains,
                    operation_readiness=resources.operation_readiness,
                    maintain=resources.maintain,
                    next_maintenance_delay=resources.next_maintenance_delay,
                )
            else:
                original_resources = resources
                resources = ComponentResources.owned(
                    original_resources.values,
                    ready=original_resources.ready,
                    close=original_resources.close,
                    internal_ports=merged_internal_ports,
                    risk_policy_bindings=original_resources.risk_policy_bindings,
                    shared_collateral_domains=original_resources.shared_collateral_domains,
                    operation_readiness=original_resources.operation_readiness,
                    maintain=original_resources.maintain,
                    next_maintenance_delay=original_resources.next_maintenance_delay,
                )
        except Exception:
            if on_resources is not None:
                on_resources(resources)
            else:
                try:
                    resources.close()
                except Exception:
                    pass
            raise ServiceComponentError("TRUSTED_PROVIDER_SESSION_INJECTION_INVALID") from None
    try:
        if on_resources is not None and not defer_resource_tracking:
            # Track before validation or adapter construction can fail.
            on_resources(resources)
            tracked_by_caller = True
        public_ports = frozenset(prepared.operations_by_port)
        expected_keys = builtin.resource_keys if public_ports else frozenset()
        if (
            spec.component == "gateway"
            and spec.options.get("role") == "trading_owner"
            and "service.account_read" in public_ports
        ):
            expected_keys = expected_keys | {"read_service"}
        expected_keys = expected_keys | builtin.optional_resource_keys.intersection(
            resources.values
        )
        if (
            spec.component == "execution"
            and spec.options.get("role") == "account_owner"
            and "service.order_query" in public_ports
            and "account_books" in resources.values
        ):
            if resources.values["account_books"] is None:
                raise ServiceComponentError("INVALID_ACCOUNT_BOOK_RESOURCES")
            expected_keys = expected_keys | {"account_books"}
        if (
            spec.component == "execution"
            and spec.options.get("role") == "account_owner"
            and "service.order_entry" in public_ports
            and "paper_owner_domain" in resources.values
        ):
            if resources.values["paper_owner_domain"] is None:
                raise ServiceComponentError("INVALID_PAPER_OWNER_DOMAIN_RESOURCE")
            expected_keys = expected_keys | {"paper_owner_domain"}
        if (
            spec.component == "execution"
            and spec.options.get("role") == "account_owner"
            and "service.order_entry" in public_ports
            and spec.options.get("approved_target_required") is True
            and "approved_target_authority" not in resources.values
        ):
            raise ServiceComponentError("APPROVED_TARGET_AUTHORITY_REQUIRED")
        if (
            spec.component == "execution"
            and spec.options.get("role") == "account_owner"
            and "service.order_entry" in public_ports
            and "approved_target_authority" in resources.values
        ):
            if resources.values["approved_target_authority"] is None:
                raise ServiceComponentError("INVALID_APPROVED_TARGET_AUTHORITY_RESOURCE")
            expected_keys = expected_keys | {"approved_target_authority"}
        if (
            spec.component == "execution"
            and spec.options.get("role") == "account_owner"
            and "service.order_entry" in public_ports
            and "strategy_ledger" in prepared.options
        ):
            # Host strategy ledger (iteration 60 R2-E): the reconciliation
            # evidence is a subscription-fed position state from the host.
            if resources.values.get("strategy_ledger_positions") is None:
                raise ServiceComponentError("STRATEGY_LEDGER_POSITIONS_REQUIRED")
            if (
                "approved_target_authority" in resources.values
                or _RECOVERY_CLOSE_OPERATION in resources.operation_readiness
            ):
                raise ServiceComponentError("STRATEGY_LEDGER_COMPOSITION_UNSUPPORTED")
            expected_keys = expected_keys | {"strategy_ledger_positions"}
        if (
            spec.component == "risk"
            and spec.options.get("role") == "account_owner"
            and "service.order_entry" in public_ports
            and "strategy_ledger" in prepared.options
        ):
            # The Risk owner's host strategy ledger (iteration 60 R3): the same
            # subscription-fed reconciliation evidence as the Execution owner.
            if resources.values.get("strategy_ledger_positions") is None:
                raise ServiceComponentError("STRATEGY_LEDGER_POSITIONS_REQUIRED")
            expected_keys = expected_keys | {"strategy_ledger_positions"}
        if (
            spec.options.get("role") == "account_owner"
            and spec.component in {"execution", "risk"}
            and "service.order_entry" in public_ports
            and "command_bindings" in resources.values
        ):
            # Typed orders.submit/orders.cancel bindings (iteration 60 WP6).
            if resources.values["command_bindings"] is None:
                raise ServiceComponentError("INVALID_COMMAND_BINDINGS_RESOURCE")
            expected_keys = expected_keys | {"command_bindings"}
        if (
            spec.component == "execution"
            and spec.options.get("role") == "group_coordinator"
            and "group_admission" in resources.values
        ):
            if resources.values["group_admission"] is None:
                raise ServiceComponentError("GROUP_POLICY_RESOURCE_INVALID")
            expected_keys = expected_keys | {"group_admission"}
        if set(resources.values) != set(expected_keys):
            raise ServiceComponentError("RESOURCE_KEYS_MISMATCH")
        group_compensation_source: object | None = None
        group_compensation_policy: TrustedGroupWritePolicy | None = None
        group_roll_exit_source: object | None = None
        group_roll_exit_policy: TrustedGroupWritePolicy | None = None
        if spec.component == "risk" and spec.options.get("role") == "account_owner":
            candidate_source = resources.values.get(
                "group_compensation_authorization_source"
            )
            if (
                "group_compensation_authorization_source" in resources.values
                and candidate_source is None
            ):
                raise ServiceComponentError("GROUP_COMPENSATION_SOURCE_UNAVAILABLE")
            compensation_policies = tuple(
                policy
                for policy in trusted_group_write_policies
                if policy.operation == _GROUP_COMPENSATION_SUBMIT
                and policy.instance_id == spec.instance_id
            )
            if candidate_source is not None:
                if (
                    prepared.operations_by_port.get("service.order_entry") is None
                    or prepared.operations_by_port["service.order_entry"].intersection(
                        {"orders.submit_group_compensation_close"}
                    )
                    != {"orders.submit_group_compensation_close"}
                    or prepared.operations_by_port.get("service.order_query") is None
                    or not {
                        "orders.prepare_group_compensation_close",
                        "orders.query_group_compensation_close",
                    }.issubset(
                        prepared.operations_by_port["service.order_query"]
                    )
                ):
                    raise ServiceComponentError("GROUP_COMPENSATION_ROUTE_UNAVAILABLE")
                try:
                    source_module = importlib.import_module(
                        "bt_api_py.service_execution_group_compensation_source"
                    )
                    source_type = getattr(
                        source_module, "GroupCompensationAuthorizationSourceV1"
                    )
                    if (
                        not isinstance(source_type, type)
                        or type(candidate_source) is not source_type
                        or candidate_source.ready is not True
                    ):
                        raise TypeError
                except Exception:
                    raise ServiceComponentError(
                        "GROUP_COMPENSATION_SOURCE_UNAVAILABLE"
                    ) from None
                if (
                    type(service_identity) is not WireIdentity
                    or service_identity.role is not WireRole.SERVICE
                ):
                    raise ServiceComponentError("GROUP_COMPENSATION_SERVICE_IDENTITY_REQUIRED")
                matches = compensation_policies
                if (
                    len(matches) != 1
                    or matches[0].instance_id != spec.instance_id
                    or matches[0].identity.role is not WireRole.SERVICE
                    or matches[0].identity.principal_ref
                    != candidate_source.coordinator_principal_ref
                    or matches[0].principal_ref
                    != candidate_source.coordinator_principal_ref
                ):
                    raise ServiceComponentError("GROUP_COMPENSATION_WRITE_POLICY_REQUIRED")
                group_compensation_source = candidate_source
                group_compensation_policy = matches[0]
            elif compensation_policies:
                raise ServiceComponentError("GROUP_COMPENSATION_SOURCE_UNAVAILABLE")
            candidate_roll_source = resources.values.get("group_roll_exit_authorization_source")
            if (
                "group_roll_exit_authorization_source" in resources.values
                and candidate_roll_source is None
            ):
                raise ServiceComponentError("GROUP_ROLL_EXIT_SOURCE_UNAVAILABLE")
            roll_policies = tuple(
                policy
                for policy in trusted_group_write_policies
                if policy.operation == _GROUP_ROLL_EXIT_SUBMIT
                and policy.instance_id == spec.instance_id
            )
            if candidate_roll_source is not None:
                if (
                    prepared.operations_by_port.get("service.order_entry") is None
                    or _GROUP_ROLL_EXIT_SUBMIT
                    not in prepared.operations_by_port["service.order_entry"]
                    or prepared.operations_by_port.get("service.order_query") is None
                    or not {
                        "orders.prepare_group_roll_exit",
                        "orders.query_group_roll_exit",
                    }.issubset(prepared.operations_by_port["service.order_query"])
                ):
                    raise ServiceComponentError("GROUP_ROLL_EXIT_ROUTE_UNAVAILABLE")
                try:
                    source_module = importlib.import_module(
                        "bt_api_py.service_execution_group_roll_exit_source"
                    )
                    source_type = getattr(source_module, "GroupRollExitAuthorizationSourceV1")
                    if (
                        not isinstance(source_type, type)
                        or type(candidate_roll_source) is not source_type
                        or candidate_roll_source.ready is not True
                    ):
                        raise TypeError
                except Exception:
                    raise ServiceComponentError("GROUP_ROLL_EXIT_SOURCE_UNAVAILABLE") from None
                if type(service_identity) is not WireIdentity or service_identity.role is not WireRole.SERVICE:
                    raise ServiceComponentError("GROUP_ROLL_EXIT_SERVICE_IDENTITY_REQUIRED")
                if (
                    len(roll_policies) != 1
                    or roll_policies[0].instance_id != spec.instance_id
                    or roll_policies[0].identity.role is not WireRole.SERVICE
                    or roll_policies[0].identity.principal_ref != candidate_roll_source.coordinator_principal_ref
                    or roll_policies[0].principal_ref != candidate_roll_source.coordinator_principal_ref
                ):
                    raise ServiceComponentError("GROUP_ROLL_EXIT_WRITE_POLICY_REQUIRED")
                group_roll_exit_source = candidate_roll_source
                group_roll_exit_policy = roll_policies[0]
            elif roll_policies:
                raise ServiceComponentError("GROUP_ROLL_EXIT_SOURCE_UNAVAILABLE")
        account_risk_policy_bindings, account_risk_policy_required_ports = (
            _account_risk_policy_metadata(
                resources,
                spec=spec,
                options=prepared.options,
                module=prepared.module,
            )
        )
        if any(port not in builtin.internal_ports for port in resources.internal_ports):
            raise ServiceComponentError("UNSUPPORTED_INTERNAL_PORT")
        if any(port not in spec.bind_ports for port in resources.internal_ports):
            raise ServiceComponentError("UNDECLARED_INTERNAL_PORT")

        adapter: object | None = None
        trading_read_adapter: object | None = None
        trading_read_module: object | None = None
        account_worker: object | None = None
        risk_position_owner: object | None = None
        account_worker_selected = (
            spec.component == "gateway"
            and spec.options.get("role") == "account_session_worker"
            and "service.provider_session" in resources.internal_ports
        )
        if account_worker_selected:
            try:
                worker_module = importlib.import_module("bt_api_gateway.account_session_worker")
            except Exception:
                raise ServiceComponentError("ACCOUNT_SESSION_WORKER_UNAVAILABLE") from None
            worker_type = getattr(worker_module, "GatewayAccountSessionWorker", None)
            account_worker = resources.internal_ports["service.provider_session"]
            if not isinstance(worker_type, type) or type(account_worker) is not worker_type:
                raise ServiceComponentError("ACCOUNT_SESSION_WORKER_INVALID")
            start_worker = getattr(account_worker, "start", None)
            worker_maintain = getattr(account_worker, "maintain", None)
            if not callable(start_worker) or not callable(worker_maintain):
                raise ServiceComponentError("ACCOUNT_SESSION_WORKER_INVALID")

        if public_ports:
            values = resources.values
            module = prepared.module
            if spec.component == "gateway":
                if spec.options.get("role") == "market_hub":
                    constructor = getattr(module, "GatewayMarketService", None)
                    adapter = constructor(
                        values["hub"],
                        enable_bounded_read_after=prepared.options.get(
                            "bounded_read_after", False
                        ),
                    )
                elif spec.options.get("role") == "trading_owner":
                    adapter = values["binding"]
                    if type(adapter) is not module.GatewayDirectServiceBinding:
                        raise ServiceComponentError("INVALID_DIRECT_BINDING")
                    if (
                        prepared.options.get("dispatch_enabled") is True
                        and "direct.dispatch" not in adapter.supported_operations
                    ):
                        raise ServiceComponentError("DIRECT_OWNER_REQUIRED")
                    if "service.account_read" in public_ports:
                        try:
                            trading_read_module = importlib.import_module(
                                "bt_api_gateway.service_component"
                            )
                            model_module = importlib.import_module(
                                "bt_api_gateway.account_read_model"
                            )
                            trading_read_adapter = values["read_service"]
                            if (
                                type(trading_read_adapter)
                                is not trading_read_module.GatewayReadService
                                or type(trading_read_adapter.state_source)
                                is not model_module.GatewayAccountReadModel
                                or trading_read_adapter.state_source.journal_account_scope
                                != adapter.account_scope
                                or set(trading_read_adapter.accounts) != {adapter.account_scope}
                                or trading_read_adapter.accounts[adapter.account_scope].account_ref
                                != adapter.account_scope
                                or trading_read_adapter.accounts[
                                    adapter.account_scope
                                ].journal_account_scope != adapter.account_scope
                                or trading_read_adapter.supported_operations
                                != module.ACCOUNT_READ_OPERATIONS
                            ):
                                raise ValueError
                        except Exception:
                            raise ServiceComponentError("INVALID_ACCOUNT_READ_BINDING") from None
                else:
                    constructor = getattr(module, "GatewayReadService", None)
                    constructor_args = {
                        "accounts": values["accounts"],
                        "principals": values["principals"],
                    }
                    if account_worker is not None:
                        constructor_args["state_worker"] = account_worker
                    if prepared.options.get("reconciliation_cut") is True:
                        inspector = resources.internal_ports.get("service.reconciliation")
                        if inspector is None or account_worker is None:
                            raise ServiceComponentError("RECONCILIATION_INSPECTOR_REQUIRED")
                        constructor_args["reconciliation"] = inspector
                    adapter = constructor(values["journal"], **constructor_args)
            elif spec.component == "monitor":
                if spec.options.get("role") == "control":
                    constructor = getattr(module, "MonitorControlRuntime", None)
                    adapter = constructor(values["service"], values["owners"])
                elif spec.options.get("role") == "telemetry_ingress":
                    constructor = getattr(module, "MonitorTelemetryService", None)
                    constructor_options = dict(prepared.options)
                    constructor_options.pop("role", None)
                    adapter = constructor(values["targets"], **constructor_options)
                elif spec.options.get("role") == "durable_ingress":
                    constructor = getattr(module, "MonitorIngressService", None)
                    constructor_options = dict(prepared.options)
                    constructor_options.pop("role", None)
                    adapter = constructor(
                        values["outbox"], values["targets"], **constructor_options
                    )
                else:
                    constructor = getattr(module, "MonitorReadService", None)
                    adapter = constructor(values["outbox"], values["targets"])
            elif spec.component == "risk" and spec.options.get("role") == "group_reservations":
                if not trusted_group_reservation_policies or any(
                    policy.instance_id != spec.instance_id
                    for policy in trusted_group_reservation_policies
                ):
                    raise ServiceComponentError("GROUP_RESERVATION_POLICY_REQUIRED")
                bundle = _group_runtime_bundle(values["group_runtime_bundle"])
                targets = bundle.reservation_targets  # type: ignore[attr-defined]
                risk_admission = bundle.risk_admission  # type: ignore[attr-defined]
                if any(
                    getattr(target, "admission", None) is not risk_admission
                    or bundle.reservation_target_for(wire_scope) is not target  # type: ignore[attr-defined]
                    for wire_scope, target in targets.items()
                ):
                    raise ServiceComponentError("GROUP_RUNTIME_BUNDLE_INVALID")
                constructor = getattr(module, "GroupReservationsService", None)
                adapter = constructor(
                    targets,
                    values["accepted_group_store"],
                    trusted_group_reservation_policies,
                )
            elif spec.component == "risk" and spec.options.get("role") == "account_owner":
                if "service.order_entry" in spec.bind_ports:
                    # Share the account-owner sidecar exclusion with the
                    # Execution adapter before recovery or provider work.
                    execution_owner_lock = _acquire_execution_owner_lock(values["journal"])
                constructor = getattr(module, "RiskOrderEntryService", None)
                risk_command_bindings = (
                    _order_command_bindings(spec, values, service_identity, risk=True)
                    if "service.order_entry" in spec.bind_ports
                    else None
                )
                risk_command_args = (
                    {}
                    if risk_command_bindings is None
                    else {"command_bindings": risk_command_bindings}
                )
                risk_targets = values["targets"]
                if prepared.options.get("strategy_client_order_prefix") is True:
                    # Strategy-attributed provider client order ids (iteration
                    # 60 R3) for Gateway execution-event routing.
                    if not isinstance(risk_targets, Mapping):
                        raise ServiceComponentError("RISK_TARGETS_INVALID")
                    risk_targets = {
                        scope: dataclasses.replace(target, strategy_client_order_prefix=True)
                        for scope, target in risk_targets.items()
                    }
                risk_ledger = None
                if "strategy_ledger" in prepared.options and "service.order_entry" in (
                    spec.bind_ports
                ):
                    from bt_api_py.service_strategy_ledger_host import (
                        ServiceStrategyLedgerBinding,
                        ServiceStrategyLedgerError,
                    )

                    try:
                        risk_ledger = ServiceStrategyLedgerBinding.for_risk_journal(
                            prepared.options["strategy_ledger"],
                            journal=values["journal"],
                            targets=risk_targets,
                            account_positions=values["strategy_ledger_positions"],
                        )
                    except ServiceStrategyLedgerError as error:
                        raise ServiceComponentError(error.code) from None
                    risk_command_args["strategy_ledger"] = risk_ledger
                try:
                    adapter = constructor(
                        values["bt_api"],
                        risk_targets,
                        values["admission"],
                        values["journal"],
                        values["gate"],
                        values["provider_contracts"],
                        group_compensation_source=group_compensation_source,
                        group_compensation_policy=group_compensation_policy,
                        group_roll_exit_authorization_source=group_roll_exit_source,
                        group_roll_exit_policy=group_roll_exit_policy,
                        dispatch_quota_admission=values.get("dispatch_quota_admission"),
                        **risk_command_args,
                    )
                except BaseException:
                    if risk_ledger is not None:
                        risk_ledger.close()
                    raise
                if risk_ledger is not None:
                    adapter_close_before_resources = adapter.close
                if (
                    "service.order_entry" in spec.bind_ports
                    and getattr(values["gate"].policy, "exposure_dimension_limits", ())
                ):
                    if (
                        spec.options.get("provider_session_ref") is None
                        or "service.provider_session" not in resources.internal_ports
                    ):
                        raise ServiceComponentError("RISK_POSITION_SOURCE_REQUIRED")
                    try:
                        bridge_module = importlib.import_module(
                            "bt_api_py.service_risk_position_snapshot"
                        )
                        owner_factory = getattr(
                            bridge_module, "build_risk_position_snapshot_owner", None
                        )
                        if not callable(owner_factory):
                            raise TypeError
                        risk_position_owner = owner_factory(
                            worker=resources.internal_ports["service.provider_session"],
                            journal=values["journal"],
                            gate=values["gate"],
                            targets=values["targets"],
                            notional_unit=values["gate"].policy.notional_unit,
                            valuation_resolver=values.get("position_valuation_resolver"),
                        )
                        risk_position_owner.prime()
                    except Exception:
                        raise ServiceComponentError(
                            "RISK_POSITION_BASELINE_UNAVAILABLE"
                        ) from None
                if "service.order_entry" in spec.bind_ports:
                    targets = values["targets"]
                    capability_state = getattr(adapter, "capability_state", None)
                    if (
                        not isinstance(targets, Mapping)
                        or not targets
                        or not callable(capability_state)
                    ):
                        raise ServiceComponentError("ORDER_CAPABILITY_UNAVAILABLE")
                    for target_scope in targets:
                        state = capability_state(target_scope)
                        if not isinstance(state, Mapping) or state.get("orders.submit") is not True:
                            raise ServiceComponentError("ORDER_CAPABILITY_UNAVAILABLE")
                    recover = getattr(adapter, "recover_interrupted_dispatches", None)
                    if not callable(recover):
                        raise ServiceComponentError("ORDER_RECOVERY_UNAVAILABLE")
                    try:
                        # Recovery completes before capabilities become ready.
                        recovered = recover()
                        if risk_ledger is not None:
                            # Then the ledger catches up and releases
                            # reservations the Risk journal never recorded.
                            adapter.recover_strategy_ledger()
                    except Exception:
                        raise ServiceComponentError("ORDER_RECOVERY_FAILED") from None
                    record_type = getattr(module, "RiskOrderCommand", None)
                    if type(recovered) is not tuple or not isinstance(record_type, type):
                        raise ServiceComponentError("ORDER_RECOVERY_INVALID")
                    try:
                        expected_scope_keys = {
                            target.account_scope.key for target in targets.values()
                        }
                        # The trusted adapter can finish a retained PROOF_READY
                        # command using its exact durable Risk receipt. Both
                        # that ACK and a still-UNKNOWN result are valid startup
                        # outcomes; this projection check grants no new proof.
                        recovery_result_valid = all(
                            type(record) is record_type
                            and record.state in {"UNKNOWN", "ACKED_TRACKED"}
                            and record.scope.key in expected_scope_keys
                            and type(record.principal_ref) is str
                            and bool(record.principal_ref)
                            and isinstance(record.latest_event, Mapping)
                            and (
                                (
                                    record.state == "UNKNOWN"
                                    and record.latest_event.get("public_state") == "UNKNOWN"
                                )
                                or (
                                    record.state == "ACKED_TRACKED"
                                    and record.latest_event.get("public_state")
                                    in {"ACKED_TRACKED", "FILLED", "CANCELLED"}
                                )
                            )
                            and (
                                record.state == "UNKNOWN"
                                or (
                                    type(record.latest_event.get("dispatch_attempt_count")) is int
                                    and record.latest_event["dispatch_attempt_count"] == 1
                                    and type(record.latest_event.get("provider_order_id")) is str
                                    and bool(record.latest_event["provider_order_id"])
                                    and type(record.permit_id) is str
                                    and bool(record.permit_id)
                                    and record.latest_event.get("permit_id") == record.permit_id
                                    and record.latest_event.get("risk_intent_id")
                                    == record.risk_intent_id
                                    and type(record.latest_event.get("proof_sha256")) is str
                                    and len(record.latest_event["proof_sha256"]) == 64
                                    and all(
                                        char in "0123456789abcdef"
                                        for char in record.latest_event["proof_sha256"]
                                    )
                                )
                            )
                            for record in recovered
                        )
                    except Exception:
                        recovery_result_valid = False
                    if not recovery_result_valid:
                        raise ServiceComponentError("ORDER_RECOVERY_INVALID")
            elif spec.component == "risk" and spec.options.get("role") == "policy_catalog":
                store_type = getattr(module, "PolicyCatalogStore", None)
                catalog = values["catalog"]
                if not isinstance(store_type, type) or type(catalog) is not store_type:
                    raise ServiceComponentError("POLICY_CATALOG_STORE_INVALID")
                constructor = getattr(module, "PolicyCatalogService", None)
                confirmation_store = None
                if "confirmed_policy_store" in values:
                    confirmation_store_type = getattr(module, "ConfirmedPolicyStore", None)
                    confirmation_store = values["confirmed_policy_store"]
                    if (
                        not isinstance(confirmation_store_type, type)
                        or type(confirmation_store) is not confirmation_store_type
                    ):
                        raise ServiceComponentError("CONFIRMED_POLICY_STORE_INVALID")
                adapter = constructor(catalog, confirmation_store=confirmation_store)
            elif (
                spec.component == "risk"
                and spec.options.get("role") == "portfolio_analytics"
            ):
                store_type = getattr(module, "AnalysisTaskStore", None)
                analysis = values["analysis"]
                if not isinstance(store_type, type) or type(analysis) is not store_type:
                    raise ServiceComponentError("ANALYSIS_STORE_INVALID")
                try:
                    profile_ref = analysis.model_profile_ref
                    modes = analysis.allowed_source_modes
                    max_tasks = analysis.max_concurrent_tasks
                    profile = analysis.model_profile
                    max_input_bytes = profile.max_input_bytes
                except Exception:
                    raise ServiceComponentError("ANALYSIS_STORE_INVALID") from None
                configured_modes = prepared.options["allowed_source_modes"]
                if (
                    type(profile_ref) is not str
                    or profile_ref != prepared.options["model_profile_ref"]
                    or type(modes) is not tuple
                    or sorted(modes) != sorted(configured_modes)
                    or type(max_tasks) is not int
                    or not 1 <= max_tasks <= 64
                    or type(max_input_bytes) is not int
                    or (
                        "max_concurrent_tasks" in prepared.options
                        and max_tasks != prepared.options["max_concurrent_tasks"]
                    )
                    or (
                        "max_input_bytes" in prepared.options
                        and max_input_bytes != prepared.options["max_input_bytes"]
                    )
                ):
                    raise ServiceComponentError("ANALYSIS_STORE_INVALID")
                constructor = getattr(module, "PortfolioAnalyticsTaskService", None)
                adapter = constructor(analysis)
            elif spec.component == "risk":
                constructor = getattr(module, "RiskReadService", None)
                adapter = constructor(values["gate"], values["targets"])
            elif spec.component == "execution" and spec.options.get("role") == "group_coordinator":
                if (
                    borrowed_upstream is None
                    or type(service_identity) is not WireIdentity
                    or service_identity.role is not WireRole.SERVICE
                ):
                    raise ServiceComponentError("GROUP_COORDINATOR_AUTHORITY_REQUIRED")
                constructor = getattr(module, "GroupCoordinatorService", None)
                adapter = constructor(
                    values["store"],
                    values["targets"],
                    values["run_bindings"],
                    borrowed_upstream,
                    service_identity,
                    group_admission=values.get("group_admission"),
                    instance_id=spec.instance_id,
                )
            elif (
                spec.component == "execution"
                and spec.options.get("role") == "legacy_import_owner"
            ):
                constructor = getattr(module, "PaperLegacyImportService", None)
                if not callable(constructor):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                try:
                    adapter = constructor(
                        values["store"],
                        values["targets"],
                        values["legacy_import_domain"],
                        writer_id=spec.instance_id,
                    )
                except Exception:
                    raise ServiceComponentError("LEGACY_IMPORT_OWNER_INVALID") from None
            elif (
                spec.component == "execution" and spec.options.get("role") == "group_account_owner"
            ):
                submit_policies = tuple(
                    policy
                    for policy in trusted_group_write_policies
                    if policy.operation == "orders.submit_group_leg"
                )
                cancel_policies = tuple(
                    policy
                    for policy in trusted_group_write_policies
                    if policy.operation == "orders.cancel_group_leg"
                )
                if (
                    not submit_policies
                    or not trusted_group_resolution_policies
                    or any(
                        policy.instance_id != spec.instance_id for policy in submit_policies
                    )
                    or any(
                        policy.instance_id != spec.instance_id for policy in cancel_policies
                    )
                    or any(
                        policy.instance_id != spec.instance_id
                        for policy in trusted_group_resolution_policies
                    )
                ):
                    raise ServiceComponentError("GROUP_ACCOUNT_OWNER_POLICIES_REQUIRED")
                writes = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.scope.account_ref,
                    )
                    for policy in submit_policies
                    if policy.instance_id == spec.instance_id
                }
                cancel_keys = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.scope.account_ref,
                    )
                    for policy in cancel_policies
                    if policy.instance_id == spec.instance_id
                }
                resolutions = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.account_ref,
                    )
                    for policy in trusted_group_resolution_policies
                    if policy.instance_id == spec.instance_id
                }
                if not writes or writes != resolutions or not cancel_keys.issubset(writes):
                    raise ServiceComponentError("GROUP_ACCOUNT_OWNER_POLICIES_MISMATCH")
                bundle = _group_runtime_bundle(values["group_runtime_bundle"])
                execution_targets = MappingProxyType(
                    {
                        wire_scope: proof_target.execution_scope
                        for wire_scope, proof_target in bundle.proof_targets.items()  # type: ignore[attr-defined]
                    }
                )
                constructor = getattr(module, "ExecutionGroupOrderEntryService", None)
                adapter = constructor(
                    values["store"],
                    execution_targets,
                    values["dispatch"],
                    bundle.account_scoped_admission,  # type: ignore[attr-defined]
                    values["accepted_group_store"],
                    values["group_authority"],
                    bundle.proof_source,  # type: ignore[attr-defined]
                    submit_policies,
                    trusted_group_resolution_policies,
                    writer_id=spec.instance_id,
                    trusted_cancel_policies=cancel_policies,
                )
                if "service.order_entry" in spec.bind_ports:
                    execution_owner_lock = _acquire_execution_owner_lock(values["store"])
                    recover = getattr(adapter, "recover_interrupted_dispatches", None)
                    if not callable(recover):
                        raise ServiceComponentError("ORDER_RECOVERY_UNAVAILABLE")
                    try:
                        recovered = recover()
                    except Exception:
                        raise ServiceComponentError("ORDER_RECOVERY_FAILED") from None
                    try:
                        from bt_api_execution import ExecutionRecord, ExecutionState

                        expected_scope_keys = {target.key for target in execution_targets.values()}
                        recovery_result_valid = type(recovered) is tuple and all(
                            type(record) is ExecutionRecord
                            and record.state is ExecutionState.UNKNOWN
                            and record.unknown_reason == "interrupted_order_dispatch"
                            and record.review_required is True
                            and record.scope_key in expected_scope_keys
                            for record in recovered
                        )
                    except Exception:
                        recovery_result_valid = False
                    if not recovery_result_valid:
                        raise ServiceComponentError("ORDER_RECOVERY_INVALID")
            elif (
                spec.component == "execution"
                and spec.options.get("role") == "account_group_owner"
            ):
                submit_policies = tuple(
                    policy
                    for policy in trusted_group_write_policies
                    if policy.operation == "orders.submit_group_leg"
                )
                cancel_policies = tuple(
                    policy
                    for policy in trusted_group_write_policies
                    if policy.operation == "orders.cancel_group_leg"
                )
                if (
                    not submit_policies
                    or not trusted_group_resolution_policies
                    or any(policy.instance_id != spec.instance_id for policy in submit_policies)
                    or any(policy.instance_id != spec.instance_id for policy in cancel_policies)
                    or any(
                        policy.instance_id != spec.instance_id
                        for policy in trusted_group_resolution_policies
                    )
                ):
                    raise ServiceComponentError("GROUP_ACCOUNT_OWNER_POLICIES_REQUIRED")
                writes = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.scope.account_ref,
                    )
                    for policy in submit_policies
                    if policy.instance_id == spec.instance_id
                }
                cancel_keys = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.scope.account_ref,
                    )
                    for policy in cancel_policies
                    if policy.instance_id == spec.instance_id
                }
                resolutions = {
                    (
                        policy.principal_ref,
                        policy.identity,
                        policy.scope_ref,
                        policy.scope,
                        policy.run_id,
                        policy.account_ref,
                    )
                    for policy in trusted_group_resolution_policies
                    if policy.instance_id == spec.instance_id
                }
                if not writes or writes != resolutions or not cancel_keys.issubset(writes):
                    raise ServiceComponentError("GROUP_ACCOUNT_OWNER_POLICIES_MISMATCH")

                bundle = _group_runtime_bundle(values["group_runtime_bundle"])
                group_targets = MappingProxyType(
                    {
                        wire_scope: proof_target.execution_scope
                        for wire_scope, proof_target in bundle.proof_targets.items()  # type: ignore[attr-defined]
                    }
                )
                grouped_constructor = getattr(
                    module, "ExecutionGroupOrderEntryService", None
                )
                if not callable(grouped_constructor):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                grouped = grouped_constructor(
                    values["store"],
                    group_targets,
                    values["dispatch"],
                    bundle.account_scoped_admission,  # type: ignore[attr-defined]
                    values["accepted_group_store"],
                    values["group_authority"],
                    bundle.proof_source,  # type: ignore[attr-defined]
                    submit_policies,
                    trusted_group_resolution_policies,
                    writer_id=spec.instance_id,
                    trusted_cancel_policies=cancel_policies,
                )

                admission = values["admission"]
                if not isinstance(admission, Mapping) or set(admission) - _ADMISSION_KEYS:
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                order_gate = admission.get("order_gate")
                cancel_gate = admission.get("cancel_gate")
                basic_gate = admission.get("basic_admission_gate")
                allow_unprotected = admission.get("allow_unprotected", False)
                if type(allow_unprotected) is not bool:
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                if (
                    order_gate is None
                    and cancel_gate is None
                    and basic_gate is None
                    and not allow_unprotected
                ):
                    raise ServiceComponentError("ADMISSION_POLICY_REQUIRED")
                ordinary_module = importlib.import_module(
                    "bt_api_py.service_execution_account_books"
                )
                ordinary_constructor = getattr(
                    ordinary_module, "ExecutionAccountOwnerService", None
                )
                if not callable(ordinary_constructor):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                ordinary = ordinary_constructor(
                    values["store"],
                    values["targets"],
                    values["dispatch"],
                    admission_gate=order_gate,
                    cancel_admission_gate=cancel_gate,
                    cancel_quota_admission=admission.get("cancel_quota_admission"),
                    basic_admission_gate=basic_gate,
                    allow_unprotected=allow_unprotected,
                    writer_id=spec.instance_id,
                    **{
                        key: values[key]
                        for key in ("cancel_dispatch", "cancel_before_dispatch")
                        if key in values
                    },
                )
                composite_constructor = getattr(
                    module, "ExecutionAccountGroupOwnerService", None
                )
                if not callable(composite_constructor):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                adapter = composite_constructor(
                    ordinary,
                    grouped,
                    store=values["store"],
                    targets=values["targets"],
                    dispatch=values["dispatch"],
                    writer_id=spec.instance_id,
                )
                adapter_close_before_resources = adapter.close
                execution_owner_lock = _acquire_execution_owner_lock(values["store"])
                recover = getattr(adapter, "recover_interrupted_dispatches", None)
                if not callable(recover):
                    raise ServiceComponentError("ORDER_RECOVERY_UNAVAILABLE")
                try:
                    recovered = recover()
                except Exception:
                    raise ServiceComponentError("ORDER_RECOVERY_FAILED") from None
                try:
                    from bt_api_execution import ExecutionRecord, ExecutionState

                    expected_scope_keys = {
                        target.key for target in values["targets"].values()
                    }
                    recovery_result_valid = type(recovered) is tuple and all(
                        type(record) is ExecutionRecord
                        and record.state is ExecutionState.UNKNOWN
                        and record.unknown_reason == "interrupted_order_dispatch"
                        and record.review_required is True
                        and record.scope_key in expected_scope_keys
                        for record in recovered
                    )
                except Exception:
                    recovery_result_valid = False
                if not recovery_result_valid:
                    raise ServiceComponentError("ORDER_RECOVERY_INVALID")
            elif spec.component == "execution" and spec.options.get("role") == "account_owner":
                constructor = getattr(module, "ExecutionOrderEntryService", None)
                admission = values["admission"]
                if (
                    not isinstance(admission, Mapping)
                    or set(admission) - _ACCOUNT_OWNER_ADMISSION_KEYS
                ):
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                order_gate = admission.get("order_gate")
                cancel_gate = admission.get("cancel_gate")
                basic_gate = admission.get("basic_admission_gate")
                allow_unprotected = admission.get("allow_unprotected", False)
                authorizer_keys = {
                    "position_baseline_authorizer",
                    "recovery_close_authorizer",
                }
                if any(
                    key in admission and not callable(admission[key])
                    for key in authorizer_keys
                ):
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                recovery_readiness_supplied = (
                    _RECOVERY_CLOSE_OPERATION in resources.operation_readiness
                )
                recovery_authorizer_supplied = "recovery_close_authorizer" in admission
                if (
                    recovery_readiness_supplied != recovery_authorizer_supplied
                    or (
                        recovery_readiness_supplied
                        and "position_baseline_authorizer" not in admission
                    )
                ):
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                if type(allow_unprotected) is not bool:
                    raise ServiceComponentError("INVALID_ADMISSION_RESOURCES")
                if (
                    order_gate is None
                    and cancel_gate is None
                    and basic_gate is None
                    and not allow_unprotected
                ):
                    # A provider-capable write route must not silently become
                    # unprotected; the composition root states its policy.
                    raise ServiceComponentError("ADMISSION_POLICY_REQUIRED")
                constructor_args = {
                    "admission_gate": order_gate,
                    "cancel_admission_gate": cancel_gate,
                    "cancel_quota_admission": admission.get("cancel_quota_admission"),
                    "basic_admission_gate": basic_gate,
                    "allow_unprotected": allow_unprotected,
                    "account_books_source": values.get("account_books"),
                }
                for key in authorizer_keys:
                    if key in admission:
                        constructor_args[key] = admission[key]
                if "borrowed_writer_lease" in values:
                    from bt_api_execution import WriterLease

                    borrowed_lease = values["borrowed_writer_lease"]
                    if type(borrowed_lease) is not WriterLease:
                        raise ServiceComponentError("INVALID_BORROWED_WRITER_LEASE")
                    constructor_args["borrowed_writer_lease"] = borrowed_lease
                    constructor_args["writer_id"] = borrowed_lease.owner_id
                for key in ("cancel_dispatch", "cancel_before_dispatch"):
                    if key in values:
                        constructor_args[key] = values[key]
                if "paper_owner_domain" in values:
                    constructor_args["paper_owner_domain"] = values["paper_owner_domain"]
                if "approved_target_authority" in values:
                    constructor_args["approved_target_authority"] = values[
                        "approved_target_authority"
                    ]
                command_bindings = _order_command_bindings(
                    spec, values, service_identity, risk=False
                )
                if command_bindings is not None:
                    # Typed-command bindings derived from deployment config
                    # (iteration 60 R2-B) or a validated trusted resource.
                    constructor_args["command_bindings"] = command_bindings
                ledger_binding = None
                if "strategy_ledger" in prepared.options and "service.order_entry" in (
                    public_ports
                ):
                    from bt_api_py.service_strategy_ledger_host import (
                        ServiceStrategyLedgerBinding,
                        ServiceStrategyLedgerError,
                    )

                    try:
                        ledger_binding = ServiceStrategyLedgerBinding(
                            prepared.options["strategy_ledger"],
                            store=values["store"],
                            targets=values["targets"],
                            account_positions=values["strategy_ledger_positions"],
                        )
                    except ServiceStrategyLedgerError as error:
                        raise ServiceComponentError(error.code) from None
                    constructor_args["strategy_ledger"] = ledger_binding
                try:
                    adapter = constructor(
                        values["store"],
                        values["targets"],
                        values["dispatch"],
                        **constructor_args,
                    )
                except BaseException:
                    if ledger_binding is not None:
                        ledger_binding.close()
                    raise
                if ledger_binding is not None:
                    adapter_close_before_resources = adapter.close
                if "service.order_entry" in spec.bind_ports:
                    recover = getattr(adapter, "recover_interrupted_dispatches", None)
                    if not callable(recover):
                        raise ServiceComponentError("ORDER_RECOVERY_UNAVAILABLE")
                    execution_owner_lock = _acquire_execution_owner_lock(values["store"])
                    try:
                        recovered = recover()
                    except Exception:
                        raise ServiceComponentError("ORDER_RECOVERY_FAILED") from None
                    record_type = getattr(module, "ExecutionRecord", None)
                    state_type = getattr(module, "ExecutionState", None)
                    targets = values.get("targets")
                    if (
                        type(recovered) is not tuple
                        or not isinstance(record_type, type)
                        or not isinstance(state_type, type)
                        or not isinstance(targets, Mapping)
                    ):
                        raise ServiceComponentError("ORDER_RECOVERY_INVALID")
                    try:
                        expected_scope_keys = {target.key for target in targets.values()}
                        recovery_result_valid = all(
                            type(record) is record_type
                            and record.state is state_type.UNKNOWN
                            and record.unknown_reason == "interrupted_order_dispatch"
                            and record.review_required is True
                            and record.scope_key in expected_scope_keys
                            for record in recovered
                        )
                    except Exception:
                        recovery_result_valid = False
                    if not recovery_result_valid:
                        raise ServiceComponentError("ORDER_RECOVERY_INVALID")
            elif spec.component == "execution":
                constructor = getattr(module, "ExecutionReadService", None)
                adapter = constructor(values["store"], values["targets"])
            else:  # pragma: no cover - fixed table and branch must stay aligned.
                raise ServiceComponentError("UNKNOWN_COMPONENT")
            if not callable(getattr(adapter, "handle", None)):
                raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")

        internal_ports = dict(resources.internal_ports)
        if (
            spec.component == "risk"
            and "service.order_admission" in spec.bind_ports
            and "service.order_admission" not in internal_ports
        ):
            gate = resources.values.get("gate")
            admission = getattr(adapter, "order_admission", None)
            if gate is None or admission is None:
                raise ServiceComponentError("INTERNAL_PORT_UNAVAILABLE")
            internal_ports["service.order_admission"] = admission

        missing_internal = {
            port
            for port in spec.bind_ports
            if port in builtin.internal_ports and port not in internal_ports
        }
        if missing_internal:
            raise ServiceComponentError("INTERNAL_PORT_UNAVAILABLE")

        if spec.component == "risk" and spec.options.get("role") == "group_policy":
            admission = internal_ports.get("service.group_admission")
            gate_type = getattr(prepared.module, "GroupPolicyService", None)
            if not isinstance(gate_type, type) or type(admission) is not gate_type:
                raise ServiceComponentError("GROUP_POLICY_RESOURCE_INVALID")
            if admission.group_policy_ref != prepared.options.get("group_policy_ref"):
                raise ServiceComponentError("GROUP_POLICY_REF_MISMATCH")
            if admission.ready is not True:
                raise ServiceComponentError("GROUP_POLICY_UNAVAILABLE")

        if (
            _RECOVERY_CLOSE_OPERATION in resources.operation_readiness
            and _RECOVERY_CLOSE_OPERATION
            not in prepared.operations_by_port.get("service.order_entry", frozenset())
        ):
            raise ServiceComponentError("RESTRICTED_OPERATION_UNAVAILABLE")

        capabilities: list[ServiceCapability] = []
        all_operations: set[str] = set()
        for port, operations in prepared.operations_by_port.items():
            if (
                spec.component == "gateway"
                and spec.options.get("role") == "trading_owner"
                and port == "service.direct_write"
            ):
                configured = getattr(adapter, "supported_operations", None)
                if type(configured) is not frozenset or configured not in (
                    prepared.module.STORAGE_OPERATIONS, prepared.module.SUPPORTED_OPERATIONS,
                    prepared.module.STORAGE_OPERATIONS | prepared.module.EVENT_OPERATIONS,
                    prepared.module.SUPPORTED_OPERATIONS | prepared.module.EVENT_OPERATIONS,
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured)
            if spec.component == "gateway" and spec.options.get("role") == "account_session_worker":
                configured_operations = getattr(adapter, "supported_operations", None)
                expected_operations = frozenset(prepared.module.SUPPORTED_OPERATIONS)
                if account_worker is None:
                    # Without a state worker the adapter has no typed snapshot
                    # source either (gateway service_component.supported_operations).
                    expected_operations = expected_operations - {"account.snapshot.typed"}
                if account_worker is None or not account_worker.instrument_metadata_available:
                    expected_operations = expected_operations - {"account.instrument_metadata"}
                if prepared.options.get("reconciliation_cut") is True:
                    expected_operations = expected_operations | {"account.reconciliation_cut"}
                if (
                    type(configured_operations) is not frozenset
                    or configured_operations != expected_operations
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if spec.component == "execution" and spec.options.get("role") == "account_owner":
                configured_operations = getattr(adapter, "supported_operations", None)
                expected_operations = frozenset(
                    {"orders.submit", "orders.cancel", "orders.query", "owner.cancel"}
                )
                if (
                    _RECOVERY_CLOSE_OPERATION
                    in frozenset(getattr(prepared.module, "SUPPORTED_OPERATIONS", ()))
                    and _RECOVERY_CLOSE_OPERATION in resources.operation_readiness
                    and "recovery_close_authorizer" in values["admission"]
                ):
                    expected_operations = expected_operations | {
                        _RECOVERY_CLOSE_OPERATION
                    }
                if "account_books" in resources.values or (
                    "strategy_ledger" in prepared.options
                    and "service.order_entry" in prepared.operations_by_port
                ):
                    expected_operations = expected_operations | {"execution.account_books.query"}
                if "approved_target_authority" in resources.values:
                    expected_operations = expected_operations | {
                        "orders.submit_approved_target",
                        "owner.reduce",
                    }
                if (
                    type(configured_operations) is not frozenset
                    or configured_operations != expected_operations
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
                if _RECOVERY_CLOSE_OPERATION not in resources.operation_readiness:
                    # The built-in adapter can implement recovery close, but
                    # it is a restricted capability: expose it only when the
                    # trusted resource provider explicitly supplies its
                    # operation readiness callback.
                    operations = operations - {_RECOVERY_CLOSE_OPERATION}
            if (
                spec.component == "risk"
                and spec.options.get("role") == "account_owner"
                and group_compensation_source is None
            ):
                # Risk compensation routes are an optional, separately
                # composed owner capability. A normal account owner never
                # advertises them without their verified store-backed source.
                operations = operations - (
                    _GROUP_COMPENSATION_OPERATIONS & operations
                )
            if (
                spec.component == "risk"
                and spec.options.get("role") == "account_owner"
                and group_roll_exit_source is None
            ):
                operations = operations - (_GROUP_ROLL_EXIT_OPERATIONS & operations)
            if spec.component == "risk" and spec.options.get("role") == "group_reservations":
                configured_operations = getattr(adapter, "supported_operations", None)
                if type(
                    configured_operations
                ) is not frozenset or configured_operations != frozenset(
                    prepared.module.SUPPORTED_OPERATIONS
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if spec.component == "risk" and spec.options.get("role") == "policy_catalog":
                configured_operations = getattr(adapter, "supported_operations", None)
                if type(
                    configured_operations
                ) is not frozenset or configured_operations != frozenset(
                    prepared.module.SUPPORTED_OPERATIONS
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if (
                spec.component == "risk"
                and spec.options.get("role") == "portfolio_analytics"
            ):
                configured_operations = getattr(adapter, "supported_operations", None)
                if type(
                    configured_operations
                ) is not frozenset or configured_operations != frozenset(
                    prepared.module.SUPPORTED_OPERATIONS
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if spec.component == "execution" and spec.options.get("role") in {
                "group_coordinator",
                "group_account_owner",
                "account_group_owner",
            }:
                configured_operations = getattr(adapter, "supported_operations", None)
                role_operations_attribute = {
                    "group_coordinator": "GROUP_COORDINATOR_OPERATIONS",
                    "group_account_owner": "GROUP_ACCOUNT_OWNER_OPERATIONS",
                    "account_group_owner": "SUPPORTED_OPERATIONS",
                }[spec.options["role"]]
                expected_operations = frozenset(
                    getattr(
                        prepared.module,
                        role_operations_attribute,
                        frozenset(),
                    )
                )
                if (
                    type(configured_operations) is not frozenset
                    or configured_operations != expected_operations
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if (
                spec.component == "execution"
                and spec.options.get("role") == "legacy_import_owner"
            ):
                configured_operations = getattr(adapter, "supported_operations", None)
                expected_operations = frozenset(prepared.module.SUPPORTED_OPERATIONS)
                if (
                    type(configured_operations) is not frozenset
                    or configured_operations != expected_operations
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = operations.intersection(configured_operations)
            if spec.component == "gateway" and spec.options.get("role") == "market_hub":
                configured_operations = getattr(adapter, "supported_operations", None)
                if type(configured_operations) is not frozenset or configured_operations not in (
                    operations,
                    operations - {"market.history"},
                ):
                    raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
                operations = configured_operations
            if operations.intersection(all_operations):
                raise ServiceComponentError("DUPLICATE_COMPONENT_OPERATION")
            all_operations.update(operations)
            write_operations = prepared.write_operations_by_port[port]
            if spec.component == "gateway" and spec.options.get("role") == "trading_owner":
                write_operations = write_operations.intersection(operations)
            if (
                spec.component == "execution"
                and spec.options.get("role") == "account_owner"
            ):
                write_operations = write_operations.intersection(operations)
            if (
                spec.component == "execution"
                and spec.options.get("role") == "account_owner"
                and port == "service.owner_control"
            ):
                write_operations = write_operations.intersection(operations)
            if (
                spec.component == "risk"
                and spec.options.get("role") == "account_owner"
                and port == "service.order_entry"
            ):
                write_operations = write_operations.intersection(operations)
            if not write_operations.issubset(operations):
                raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
            capabilities.append(
                ServiceCapability(spec.instance_id, port, operations, write_operations)
            )

        handlers: dict[
            str,
            Callable[[ServiceCallContext, Mapping[str, Any]], Mapping[str, Any]],
        ] = {}
        registration_bound = (
            spec.component == "gateway" and spec.options.get("role") == "market_hub"
        )
        market_registration_type = (
            getattr(prepared.module, "GatewayMarketRegistration", None)
            if registration_bound
            else None
        )
        market_authorization_error_types = tuple(
            error_type
            for error_type in (
                getattr(prepared.module, "GatewayMarketHubError", None)
                if registration_bound
                else None,
                getattr(prepared.module, "GatewayMarketServiceError", None)
                if registration_bound
                else None,
            )
            if isinstance(error_type, type) and issubclass(error_type, Exception)
        )
        market_service_error_type = (
            getattr(prepared.module, "GatewayMarketServiceError", None)
            if registration_bound
            else None
        )
        gateway_event_journal_error_type = (
            getattr(
                trading_read_module if trading_read_module is not None else prepared.module,
                "GatewayEventJournalError",
                None,
            )
            if spec.component == "gateway"
            else None
        )
        if registration_bound and (
            market_registration_type is None
            or len(market_authorization_error_types) != 2
            or len(set(market_authorization_error_types)) != 2
            or not callable(getattr(adapter, "register_registration", None))
        ):
            raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
        for operation in all_operations:

            def handler(
                context: ServiceCallContext,
                arguments: Mapping[str, Any],
                *,
                _adapter: object = adapter,
                _operation: str = operation,
            ) -> Mapping[str, Any]:
                assert _adapter is not None
                if spec.component == "gateway" and spec.options.get("role") == "trading_owner":
                    if _operation in prepared.module.SUPPORTED_OPERATIONS | prepared.module.EVENT_OPERATIONS:
                        return _adapter.handle(_operation, context=context, arguments=arguments)
                    _adapter = trading_read_adapter
                    assert _adapter is not None
                if registration_bound:
                    try:
                        registration = market_registration_type(
                            principal_ref=context.principal_ref,
                            execution_domain_ref=context.scope.execution_domain_ref,
                            strategy_ref=context.scope.strategy_ref,
                            run_id=context.scope.run_id,
                            account_ref=context.scope.account_ref,
                        )
                        _adapter.register_registration(  # type: ignore[attr-defined]
                            context.registration_id, registration
                        )
                        return _adapter.handle(  # type: ignore[attr-defined]
                            _operation,
                            principal_ref=context.principal_ref,
                            scope=context.scope,
                            arguments=arguments,
                            registration_id=context.registration_id,
                            result_fits=context.result_fits,
                        )
                    except Exception as error:
                        if (
                            _operation == "market.read_after_bounded"
                            and isinstance(market_service_error_type, type)
                            and type(error) is market_service_error_type
                            and getattr(error, "code", None) == "REPLAY_PAGE_TOO_LARGE"
                        ):
                            raise ServiceResultTooLargeError() from None
                        if (
                            _operation
                            in {
                                "market.subscribe",
                                "market.head",
                                "market.snapshot",
                                "market.read_after",
                                "market.read_after_bounded",
                            }
                            and type(error) in market_authorization_error_types
                            and getattr(error, "code", None)
                            in {"MARKET_KEY_DENIED", "MARKET_KEY_NOT_EXPORTED"}
                        ):
                            raise ServiceOperationDeniedError() from None
                        raise
                if spec.component == "gateway":
                    try:
                        return _adapter.handle(  # type: ignore[attr-defined]
                            _operation,
                            principal_ref=context.principal_ref,
                            identity=context.identity,
                            scope=context.scope,
                            arguments=arguments,
                            result_fits=context.result_fits,
                        )
                    except Exception as error:
                        if (
                            _operation == "account.read_after"
                            and isinstance(gateway_event_journal_error_type, type)
                            and type(error) is gateway_event_journal_error_type
                            and getattr(error, "code", None) == "CONSUMER_PAGE_TOO_LARGE"
                        ):
                            raise ServiceResultTooLargeError() from None
                        raise
                if spec.component == "monitor" and spec.options.get("role") == "control":
                    try:
                        return _adapter.handle(  # type: ignore[attr-defined]
                            _operation,
                            principal_ref=context.principal_ref,
                            identity=context.identity,
                            scope=context.scope,
                            arguments=arguments,
                        )
                    except Exception as error:
                        if type(error) is getattr(
                            prepared.module, "MonitorControlServiceError", None
                        ) and error.code in {
                            "CONTROL_NOT_AUTHORIZED",
                            "CALLER_DELEGATION_NOT_GRANTED",
                            "APPLICATION_ROLE_REQUIRED",
                            "INVALID_IDENTITY",
                            "IDENTITY_MISMATCH",
                            "INVALID_SCOPE",
                            "UNSUPPORTED_SCOPE",
                            "SCOPE_NOT_GRANTED",
                            "COMMAND_NOT_FOUND",
                        }:
                            # These failures precede ledger admission/effects.
                            # Owner, storage and ACK failures stay UNKNOWN.
                            raise ServiceOperationDeniedError() from None
                        raise
                if spec.component == "monitor" and spec.options.get("role") == "durable_ingress":
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        principal_ref=context.principal_ref,
                        identity=context.identity,
                        scope=context.scope,
                        arguments=arguments,
                    )
                if spec.component == "monitor" and spec.options.get("role") == "telemetry_ingress":
                    try:
                        return _adapter.handle(  # type: ignore[attr-defined]
                            _operation,
                            principal_ref=context.principal_ref,
                            identity=context.identity,
                            scope=context.scope,
                            arguments=arguments,
                            result_fits=context.result_fits,
                        )
                    except Exception as error:
                        if (
                            type(error)
                            is getattr(prepared.module, "MonitorTelemetryServiceError", None)
                            and error.code == "SNAPSHOT_TOO_LARGE"
                        ):
                            raise ServiceResultTooLargeError() from None
                        raise
                if (
                    spec.component == "execution"
                    and spec.options.get("role") == "legacy_import_owner"
                ):
                    principal_ref = context.identity.principal_ref
                    if _operation == prepared.module.PREPARE_OPERATION:
                        imported = (
                            arguments.get("imported")
                            if isinstance(arguments, Mapping)
                            else None
                        )
                        if (
                            not isinstance(imported, Mapping)
                            or imported.get("source_owner_id") != principal_ref
                        ):
                            return {
                                "ok": False,
                                "code": "SOURCE_OWNER_MISMATCH",
                                "result": {},
                            }
                    if _operation in {
                        prepared.module.ACTIVATE_OPERATION,
                        prepared.module.ABORT_OPERATION,
                    }:
                        try:
                            existing = _adapter.handle(  # type: ignore[attr-defined]
                                prepared.module.STATUS_OPERATION,
                                scope=context.scope,
                                arguments={},
                            )
                        except Exception:
                            return {
                                "ok": False,
                                "code": "IMPORT_STORE_UNAVAILABLE",
                                "result": {},
                            }
                        existing_result = (
                            existing.get("result")
                            if isinstance(existing, Mapping)
                            and isinstance(existing.get("result"), Mapping)
                            else {}
                        )
                        receipt = existing_result.get("receipt")
                        if not isinstance(existing, Mapping) or existing.get("ok") is not True:
                            return {
                                "ok": False,
                                "code": "IMPORT_STORE_UNAVAILABLE",
                                "result": {},
                            }
                        if (
                            isinstance(receipt, Mapping)
                            and receipt.get("source_owner_id") != principal_ref
                        ):
                            return {
                                "ok": False,
                                "code": "SOURCE_OWNER_MISMATCH",
                                "result": {},
                            }
                    try:
                        reply = _adapter.handle(  # type: ignore[attr-defined]
                            _operation,
                            scope=context.scope,
                            arguments=arguments,
                        )
                    except Exception:
                        return {
                            "ok": False,
                            "code": "IMPORT_STORE_UNAVAILABLE",
                            "result": {},
                        }
                    result = (
                        reply.get("result")
                        if isinstance(reply, Mapping)
                        and isinstance(reply.get("result"), Mapping)
                        else {}
                    )
                    receipt = result.get("receipt")
                    if _operation == prepared.module.STATUS_OPERATION and isinstance(
                        receipt, Mapping
                    ):
                        if receipt.get("source_owner_id") != principal_ref:
                            return {
                                "ok": False,
                                "code": "SOURCE_OWNER_MISMATCH",
                                "result": {},
                            }
                    if _operation == prepared.module.INSPECT_SOURCE_OPERATION:
                        source_receipt = result.get("source_receipt")
                        if isinstance(source_receipt, Mapping):
                            if source_receipt.get("source_owner_id") != principal_ref:
                                return {
                                    "ok": False,
                                    "code": "SOURCE_OWNER_MISMATCH",
                                    "result": {},
                                }
                    if (
                        _operation in {
                            prepared.module.PREPARE_OPERATION,
                            prepared.module.ACTIVATE_OPERATION,
                            prepared.module.ABORT_OPERATION,
                        }
                        and isinstance(reply, Mapping)
                        and reply.get("ok") is True
                        and result.get("source_owner_id") != principal_ref
                    ):
                        return {
                            "ok": False,
                            "code": "SOURCE_OWNER_MISMATCH",
                            "result": {},
                        }
                    return reply
                if spec.component == "risk" and spec.options.get("role") == "group_reservations":
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        context=context,
                        arguments=arguments,
                    )
                if spec.component == "execution" and spec.options.get("role") in {
                    "group_coordinator",
                    "group_account_owner",
                    "account_group_owner",
                }:
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        context=context,
                        arguments=arguments,
                    )
                if (
                    spec.component == "risk"
                    and spec.options.get("role") == "account_owner"
                    and _operation in _GROUP_COMPENSATION_OPERATIONS
                ):
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        context=context,
                        arguments=arguments,
                    )
                if (
                    spec.component == "risk"
                    and spec.options.get("role") == "account_owner"
                    and _operation in _GROUP_ROLL_EXIT_OPERATIONS
                ):
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        context=context,
                        arguments=arguments,
                    )
                if (
                    spec.component in {"execution", "risk"}
                    and spec.options.get("role") == "account_owner"
                ):
                    return _adapter.handle(  # type: ignore[attr-defined]
                        _operation,
                        principal_ref=context.principal_ref,
                        identity=context.identity,
                        scope=context.scope,
                        arguments=arguments,
                    )
                return _adapter.handle(  # type: ignore[attr-defined]
                    _operation,
                    principal_ref=context.principal_ref,
                    scope=context.scope,
                    arguments=arguments,
                )

            handlers[operation] = handler

        maintain = None
        maintain_registrations = None
        readiness = resources.ready
        if registration_bound:
            candidate_maintain = getattr(adapter, "maintain", None)
            if not callable(candidate_maintain):
                raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
            maintain = candidate_maintain

            def readiness(
                *,
                resource_ready: Callable[[], bool] = resources.ready,
                market_adapter: object = adapter,
            ) -> bool:
                try:
                    return resource_ready() is True and market_adapter.ready is True  # type: ignore[attr-defined]
                except Exception:
                    return False

        if account_worker is not None:

            def maintain_account_worker(
                _active_registration_ids: frozenset[str],
                *,
                maintain_worker: Callable[[], object] = worker_maintain,
            ) -> object:
                # Provider ownership belongs to the service instance, not to
                # any strategy lease. Maintain it even when no clients remain.
                return maintain_worker()

            maintain = maintain_account_worker

            def account_worker_readiness(
                *,
                resource_ready: Callable[[], bool] = resources.ready,
                session_worker: object = account_worker,
            ) -> bool:
                try:
                    return resource_ready() is True and session_worker.ready is True
                except Exception:
                    return False

            readiness = account_worker_readiness

        if spec.component == "monitor" and spec.options.get("role") == "control":
            # Signed commands are admitted by the request handler, but their
            # Risk effects belong to the existing host-owned RiskGate. Run the
            # durable monitor owner only from this normal ServiceHost hook.
            candidate_maintain = getattr(adapter, "maintain", None)
            if not callable(candidate_maintain):
                raise ServiceComponentError("MONITOR_CONTROL_OWNER_UNAVAILABLE")
            maintain = candidate_maintain

        if (
            spec.component == "risk"
            and spec.options.get("role") == "portfolio_analytics"
        ):
            # The analysis role executes its durable task queue on the host's
            # owner thread; a fixed-table role without the executor hook is a
            # build-time fault instead of a silently idle service.
            candidate_maintain = getattr(adapter, "maintain", None)
            if not callable(candidate_maintain):
                raise ServiceComponentError("BUILTIN_COMPONENT_INVALID")
            maintain = candidate_maintain

        if (
            spec.component == "execution"
            and spec.options.get("role")
            in {
                "group_coordinator",
                "group_account_owner",
                "account_group_owner",
            }
        ) or (spec.component == "risk" and spec.options.get("role") == "group_reservations") or (
            spec.component == "risk"
            and spec.options.get("role") == "account_owner"
            and group_compensation_source is not None
        ) or (
            spec.component == "risk"
            and spec.options.get("role") == "account_owner"
            and group_roll_exit_source is not None
        ):
            candidate_maintain_contexts = getattr(adapter, "maintain_registrations", None)
            if not callable(candidate_maintain_contexts):
                raise ServiceComponentError("GROUP_REGISTRATION_LIFECYCLE_UNAVAILABLE")
            maintain_registrations = candidate_maintain_contexts

            def group_component_readiness(
                *,
                resource_ready: Callable[[], bool] = resources.ready,
                group_adapter: object = adapter,
            ) -> bool:
                try:
                    return resource_ready() is True and group_adapter.ready is True  # type: ignore[attr-defined]
                except Exception:
                    return False

            readiness = group_component_readiness

        if risk_position_owner is not None:
            prior_maintain = maintain

            def maintain_risk_position_baseline(
                active_ids: frozenset[str],
                *,
                position_owner: object = risk_position_owner,
                existing_maintain: Callable[[frozenset[str]], object] | None = prior_maintain,
            ) -> None:
                if existing_maintain is not None:
                    existing_maintain(active_ids)
                position_owner.maintain(active_ids)  # type: ignore[attr-defined]

            prior_readiness = readiness

            def risk_position_readiness(
                *,
                resource_readiness: Callable[[], bool] = prior_readiness,
                position_owner: object = risk_position_owner,
            ) -> bool:
                try:
                    return (
                        resource_readiness() is True
                        and position_owner.ready is True  # type: ignore[attr-defined]
                    )
                except Exception:
                    return False

            maintain = maintain_risk_position_baseline
            readiness = risk_position_readiness

        component_resources = _resources_with_execution_owner_lock(
            resources,
            execution_owner_lock,
            before_close=adapter_close_before_resources,
        )
        operation_readiness = {
            operation: callback
            for operation, callback in resources.operation_readiness.items()
            if any(
                capability.port == _RESTRICTED_OPERATION_PORTS[operation]
                and operation in capability.write_operations
                for capability in capabilities
            )
        }
        risk_owner_gate: object | None = None
        risk_owner_targets: Mapping[WireScope, object] = {}
        risk_owner_admission: Mapping[WireScope, object] = {}
        if spec.component == "risk" and spec.options.get("role") == "account_owner":
            if "service.order_entry" in spec.bind_ports:
                risk_owner_gate = resources.values.get("gate")
                risk_owner_targets = resources.values.get("targets", {})  # type: ignore[assignment]
                risk_owner_admission = resources.values.get("admission", {})  # type: ignore[assignment]
        component = ServiceComponent(
            component=spec.component,
            instance_id=spec.instance_id,
            capabilities=tuple(capabilities),
            handlers=handlers,
            internal_ports=internal_ports,
            readiness=readiness,
            close=component_resources.close,
            maintain=maintain,
            maintain_registrations=maintain_registrations,
            maintain_resources=component_resources.maintain,
            next_maintenance_delay=component_resources.next_maintenance_delay,
            account_risk_policy_bindings=account_risk_policy_bindings,
            account_risk_policy_required_ports=account_risk_policy_required_ports,
            shared_collateral_domains=resources.shared_collateral_domains,
            risk_owner_gate=risk_owner_gate,
            risk_owner_targets=risk_owner_targets,
            risk_owner_admission=risk_owner_admission,
            operation_readiness=operation_readiness,
        )
        if on_resources is not None and defer_resource_tracking:
            # The owner lock and resource close callback must be tracked as one
            # lifecycle unit if a later host-start step needs to retry cleanup.
            on_resources(component_resources)
            tracked_by_caller = True
        execution_owner_lock_transferred = execution_owner_lock is not None
        if account_worker is not None:
            # Adapter construction above validates the provider session's
            # trusted account/journal/ACL scope bindings. Do not connect to
            # the provider until that pure construction has succeeded.
            try:
                start_worker()
            except Exception:
                raise ServiceComponentError("ACCOUNT_SESSION_WORKER_START_FAILED") from None
            try:
                if account_worker.ready is not True:
                    raise ServiceComponentError("ACCOUNT_SESSION_WORKER_NOT_READY")
            except ServiceComponentError:
                raise
            except Exception:
                raise ServiceComponentError("ACCOUNT_SESSION_WORKER_NOT_READY") from None
        return component
    except BaseException:
        if defer_resource_tracking and on_resources is not None and not tracked_by_caller:
            pending_resources = _resources_with_execution_owner_lock(
                resources,
                execution_owner_lock,
                before_close=adapter_close_before_resources,
            )
            on_resources(pending_resources)
            tracked_by_caller = True
            execution_owner_lock_transferred = execution_owner_lock is not None
        if not tracked_by_caller:
            try:
                _resources_with_execution_owner_lock(
                    resources,
                    execution_owner_lock,
                    before_close=adapter_close_before_resources,
                ).close()
                execution_owner_lock_transferred = execution_owner_lock is not None
            except Exception:
                raise ServiceComponentError("RESOURCE_CLEANUP_FAILED") from None
        if execution_owner_lock is not None and not execution_owner_lock_transferred:
            execution_owner_lock.close()
        raise


def _order_command_bindings(
    spec: ComponentSpec,
    values: Mapping[str, object],
    service_identity: WireIdentity | None,
    *,
    risk: bool,
) -> Mapping[WireScope, object] | None:
    """Typed order-command bindings of one account-owner order-entry host.

    Iteration 60 R2-B: derived in one place (``service_command_wire``) from
    the component's ``command_bindings`` deployment declaration, the trusted
    targets and, for Risk, the instrument metadata already loaded in each
    target's registry; or a trusted ``command_bindings`` resource checked by
    the same rules. The route is ``<service_id>/<instance_id>``. Missing or
    ambiguous facts refuse the component start. Without either form the host
    stays binding-less (generic, see the Base registry).
    """

    declared = spec.options.get("command_bindings")
    supplied = values.get("command_bindings")
    if declared is None and supplied is None:
        return None
    if declared is not None and supplied is not None:
        raise ServiceComponentError("COMMAND_BINDINGS_CONFLICT")
    if (
        type(service_identity) is not WireIdentity
        or service_identity.role is not WireRole.SERVICE
    ):
        raise ServiceComponentError("COMMAND_BINDING_SERVICE_IDENTITY_REQUIRED")
    from bt_api_py.service_command_wire import (
        ServiceCommandWireError,
        derive_host_command_bindings,
        risk_instrument_facts,
        validate_host_command_bindings,
    )

    targets = values.get("targets")
    if not isinstance(targets, Mapping):
        raise ServiceComponentError("COMMAND_BINDING_TARGET_INVALID")
    try:
        if supplied is not None:
            return validate_host_command_bindings(
                supplied,
                service_id=service_identity.actor_ref,
                instance_id=spec.instance_id,
                targets=targets,
            )
        facts = (
            {scope: risk_instrument_facts(target) for scope, target in targets.items()}
            if risk
            else None
        )
        return derive_host_command_bindings(
            declared,
            service_id=service_identity.actor_ref,
            instance_id=spec.instance_id,
            targets=targets,
            instrument_facts=facts,
        )
    except ServiceCommandWireError as error:
        raise ServiceComponentError(error.code) from None


def _copy_string_mapping(value: Mapping[str, object], code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ServiceComponentError(code)
    copied = dict(value)
    if any(type(key) is not str or not key for key in copied):
        raise ServiceComponentError(code)
    return copied


def _copy_callable_mapping(
    value: Mapping[str, Callable[..., Any]], code: str
) -> dict[str, Callable[..., Any]]:
    copied = _copy_string_mapping(value, code)
    if any(not callable(item) for item in copied.values()):
        raise ServiceComponentError(code)
    return copied  # type: ignore[return-value]


__all__ = [
    "BorrowedServiceClient",
    "ComponentResources",
    "ComponentSpec",
    "PreparedComponent",
    "ResourceOwnership",
    "ServiceComponent",
    "ServiceComponentError",
    "ServiceResourceProvider",
    "TrustedRiskPolicyBinding",
    "TrustedSharedCollateralDomain",
    "build_component",
    "component_specs",
    "order_components",
    "validate_components",
]
