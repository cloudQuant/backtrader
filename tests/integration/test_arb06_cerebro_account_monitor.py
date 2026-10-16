"""Real local Cerebro consumption of a relayed group-recovery Monitor event.

The group residual is produced by the accepted SDK group service and its
SQLite-backed synthetic provider, relayed by the SDK's production
``ServiceGroupMonitorRelay`` through a real Monitor ingress Host, and read by
a normal Backtrader Strategy through ``ServiceExecutionSession`` and a real
Monitor query Host. This is local synthetic-service evidence; it does not
contact an exchange or establish real-account acceptance.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import multiprocessing
import os
import socket
import sys
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# These are required sources for this acceptance node. Missing exports must
# fail collection instead of turning the real-chain case into a skip.
for _module_name in (
    "bt_api_py",
    "bt_api_base",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_transport_zmq",
):
    importlib.import_module(_module_name)
zmq = importlib.import_module("zmq")
pandas = importlib.import_module("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import GroupOrderState, Side  # noqa: E402
from bt_api_monitor.durable import DurableOutbox  # noqa: E402
from bt_api_monitor.service_component import MonitorReadTarget  # noqa: E402
from bt_api_monitor.service_ingress import MonitorIngressTarget  # noqa: E402
from bt_api_py.service_components import ComponentResources  # noqa: E402
from bt_api_py.service_config import parse_service_config  # noqa: E402
from bt_api_py.service_group_monitor import (  # noqa: E402
    ServiceGroupMonitorRelay,
    SqliteGroupResidualReader,
    group_monitor_relay_configured,
)
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority  # noqa: E402
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.service_execution_group import (  # noqa: E402
    ServiceExecutionGroupError,
    ServiceStrategyGroupRoute,
    _parse_residual_event,
    _projected_residual_event_id,
)
from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402
from tests.integration import test_btapi_execution_group_cerebro_v3_host as p5a  # noqa: E402
from tests.integration import test_btapi_execution_group_cerebro as p5a_local  # noqa: E402

_SDK_PARTIAL_FIXTURE_ENV = "BT_API_ARB06_PARTIAL_GROUP_FIXTURE"
_SDK_PARTIAL_FIXTURE_SHA256 = "2f06291dbed35bc56f54d6e502c001fd3316f9408cf4a0fab615acaff03a033e"
_SDK_PARTIAL_FIXTURE_MODULE = "_bt_api_arb06_fixed_partial_group_fixture"
_MONITOR_INGRESS_SERVICE_ID = "arb06-cerebro-monitor-ingress-service"
_MONITOR_INGRESS_INSTANCE_ID = "arb06-cerebro-monitor-ingress"
_MONITOR_INGRESS_ROOT_SCOPE_REF = "arb06-cerebro-monitor-root-v1"
_MONITOR_INGRESS_SCOPE_REF = "arb06-cerebro-monitor-ingress-scope-v1"
_MONITOR_INGRESS_LISTENER_REF = "arb06-cerebro-monitor-listener-v1"
_MONITOR_INGRESS_SECURITY_REF = "arb06-cerebro-monitor-server-curve-v1"
_MONITOR_INGRESS_PRINCIPAL = "arb06-cerebro-monitor-ingress-principal"
_MONITOR_RELAY_ID = "arb06-cerebro-group-monitor-relay"
_MONITOR_RELAY_PRINCIPAL = "arb06-cerebro-group-monitor-relay-principal"
_MONITOR_RELAY_SCOPE_REF = "arb06-cerebro-group-monitor-relay-scope-v1"
_MONITOR_RELAY_SECURITY_REF = "arb06-cerebro-group-monitor-relay-curve-v1"
_MONITOR_OUTBOX_SCOPE = "outbox:arb06-cerebro-group-residual"
_MONITOR_EVENT_TYPE = "group.residual"
_MONITOR_EVENT_TYPES = (_MONITOR_EVENT_TYPE,)
_MONITOR_INGRESS_LIMITS = {
    "max_events": 64,
    "max_bytes": 262_144,
    "max_event_bytes": 16_384,
}
_MONITOR_REQUEST_TIMEOUT_MS = 1_000
_MONITOR_MAX_MESSAGE_BYTES = 65_536
_GROUP_FIXTURE_CACHE: ModuleType | None = None


def _parser_route(
    *,
    strategy_ref: str = "strategy-a",
    portfolio_ref: str = "portfolio-a",
    account_refs: tuple[str, ...] = ("account-a", "account-b"),
    producer_principal_ref: str | None = "residual-relay-principal",
    producer_actor_ref: str | None = "residual-relay-service",
) -> ServiceStrategyGroupRoute:
    return ServiceStrategyGroupRoute(
        strategy_ref=strategy_ref,
        portfolio_ref=portfolio_ref,
        account_refs=account_refs,
        runtime=None,
        group_scope_ref="group-scope-v1",
        monitor_scope_ref="monitor-scope-v1",
        monitor_producer_principal_ref=producer_principal_ref,
        monitor_producer_actor_ref=producer_actor_ref,
    )


def _parser_projection(
    *,
    strategy_id: str = "strategy-a",
    portfolio_ref: str = "portfolio-a",
    account_refs: tuple[str, ...] = ("account-a", "account-b"),
) -> dict[str, Any]:
    return {
        "schema": "sdk.group_monitor_projection.v1",
        "journal_generation": "b" * 64,
        "source_sequence": 4,
        "source_event_sha256": "a" * 64,
        "source_revision": 7,
        "source_created_at_ns": 1_792_200_000_000_000_000,
        "portfolio_ref": portfolio_ref,
        "group_id": "group-a",
        "strategy_id": strategy_id,
        "account_refs": list(account_refs),
        "state": "RECOVERY_REQUIRED",
        "reason": "hedge_residual_unresolved",
        "residual_base_units": "3",
        "first_leg_id": "leg-a",
        "second_leg_id": "leg-b",
        "first_filled_quantity": "5",
        "second_filled_quantity": "2",
    }


def _parser_event(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sequence": 9,
        "event_id": "service-event:" + "c" * 64,
        "event_type": _MONITOR_EVENT_TYPE,
        "occurred_at": 1_792_200_000.0,
        "data": dict(data),
    }


def _canonical_ingress_data(
    projection: Mapping[str, Any],
    *,
    producer: Mapping[str, Any] | None = None,
    source_event_id: str | None = None,
) -> dict[str, Any]:
    payload = dict(projection)
    return {
        "producer": dict(
            producer
            or {
                "role": "service",
                "principal_ref": "residual-relay-principal",
                "actor_ref": "residual-relay-service",
                "delegate_ref": None,
            }
        ),
        "source_event_id": source_event_id or _projected_residual_event_id(payload),
        "payload": payload,
    }


def test_group_residual_parser_accepts_canonical_ingress_and_legacy_flat_data() -> None:
    route = _parser_route()
    projection = _parser_projection()
    flat = _parse_residual_event(_parser_event(projection), route)
    wrapped = _parse_residual_event(
        _parser_event(_canonical_ingress_data(projection)), route
    )
    assert flat == wrapped
    assert wrapped.strategy_ref == route.strategy_ref
    assert wrapped.portfolio_ref == route.portfolio_ref
    assert wrapped.account_refs == route.account_refs
    assert wrapped.source_event_sha256 == projection["source_event_sha256"]


@pytest.mark.parametrize(
    "mutation",
    ("unbound_producer", "producer_mismatch", "source_id_mismatch", "mixed_shape"),
)
def test_group_residual_parser_rejects_invalid_ingress_envelopes(mutation: str) -> None:
    projection = _parser_projection()
    ingress = _canonical_ingress_data(projection)
    route = _parser_route(
        producer_principal_ref=None if mutation == "unbound_producer" else "residual-relay-principal",
        producer_actor_ref=None if mutation == "unbound_producer" else "residual-relay-service",
    )
    if mutation == "producer_mismatch":
        ingress["producer"]["principal_ref"] = "other-service-principal"
    elif mutation == "source_id_mismatch":
        ingress["source_event_id"] = "service-event:" + "d" * 64
    elif mutation == "mixed_shape":
        ingress["strategy_id"] = "strategy-a"
    with pytest.raises(ServiceExecutionGroupError) as error:
        _parse_residual_event(_parser_event(ingress), route)
    assert error.value.code == "RESIDUAL_EVENT_INVALID"


@pytest.mark.parametrize(
    "identity_change",
    ("strategy", "portfolio", "account"),
)
def test_group_residual_parser_rejects_cross_route_payload(identity_change: str) -> None:
    route = _parser_route()
    projection = _parser_projection()
    if identity_change == "strategy":
        projection["strategy_id"] = "strategy-b"
    elif identity_change == "portfolio":
        projection["portfolio_ref"] = "portfolio-b"
    else:
        projection["account_refs"] = ["account-a", "account-c"]
    # Recreate the valid source ID for the changed SDK projection so the route
    # mismatch, rather than a stale-ID check, is what rejects the event.
    ingress = _canonical_ingress_data(projection)
    with pytest.raises(ServiceExecutionGroupError) as error:
        _parse_residual_event(_parser_event(ingress), route)
    assert error.value.code == "RESIDUAL_EVENT_INVALID"


def _load_fixed_partial_group_fixture() -> ModuleType:
    """Load the exact accepted SDK fixture blob without importing dirty checkout bytes."""

    global _GROUP_FIXTURE_CACHE
    source_text = os.environ.get(_SDK_PARTIAL_FIXTURE_ENV)
    if type(source_text) is not str or not source_text.strip():
        raise AssertionError(f"{_SDK_PARTIAL_FIXTURE_ENV} must name the fixed SDK fixture export")
    source_path = Path(source_text).resolve()
    if not source_path.is_file():
        raise AssertionError("fixed SDK partial-group fixture is missing")
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != _SDK_PARTIAL_FIXTURE_SHA256:
        raise AssertionError("fixed SDK partial-group fixture pin changed")

    if _GROUP_FIXTURE_CACHE is not None:
        loaded = Path(getattr(_GROUP_FIXTURE_CACHE, "__file__", "")).resolve()
        if loaded != source_path:
            raise AssertionError("a different SDK partial-group fixture is already loaded")
        return _GROUP_FIXTURE_CACHE

    provider_module = p5a._load_sdk_host_fixture()
    del provider_module
    spec = importlib.util.spec_from_file_location(_SDK_PARTIAL_FIXTURE_MODULE, source_path)
    if spec is None or spec.loader is None:
        raise AssertionError("fixed SDK partial-group fixture cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_SDK_PARTIAL_FIXTURE_MODULE] = module
    spec.loader.exec_module(module)
    _GROUP_FIXTURE_CACHE = module
    return module


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _monitor_ingress_service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _MONITOR_INGRESS_SERVICE_ID,
        "scope_ref": _MONITOR_INGRESS_ROOT_SCOPE_REF,
        "transport_ref": _MONITOR_INGRESS_LISTENER_REF,
        "registration_policy_ref": "arb06-cerebro-monitor-registration-v1",
        "service_requirements_ref": "arb06-cerebro-monitor-requirements-v1",
        "components": {
            "monitor": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _MONITOR_INGRESS_INSTANCE_ID,
                    "bind_ports": ["service.telemetry_ingress"],
                    "options": {"role": "durable_ingress", **_MONITOR_INGRESS_LIMITS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _MONITOR_INGRESS_LISTENER_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _MONITOR_INGRESS_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MONITOR_MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _monitor_ingress_host_entry(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    outbox_path: str,
    server_public: bytes,
    server_secret: bytes,
    relay_public: bytes,
    execution_domain_ref: str,
    strategy_ref: str,
    portfolio_ref: str,
) -> None:
    """Run one ordinary, authenticated, durable Monitor ingress ServiceHost."""

    stage = "parse_service_config"
    host = None
    outbox = None
    try:
        config = parse_service_config(raw_config)
        stage = "open_outbox"
        outbox = DurableOutbox(outbox_path)
        scope = WireScope(
            execution_domain_ref,
            account_ref="account-a",
            strategy_ref=strategy_ref,
            portfolio_ref=portfolio_ref,
        )
        service_identity = WireIdentity(
            WireRole.SERVICE,
            _MONITOR_INGRESS_PRINCIPAL,
            _MONITOR_INGRESS_SERVICE_ID,
        )
        relay_identity = WireIdentity(
            WireRole.SERVICE,
            _MONITOR_RELAY_PRINCIPAL,
            _MONITOR_RELAY_ID,
        )

        def resource_provider(component, instance_id, _options, _host_scope):
            if component != "monitor" or instance_id != _MONITOR_INGRESS_INSTANCE_ID:
                raise AssertionError("unexpected ARB06 Monitor ingress resource request")
            return ComponentResources.borrowed(
                {
                    "outbox": outbox,
                    "targets": {
                        scope: MonitorIngressTarget(
                            _MONITOR_OUTBOX_SCOPE,
                            _MONITOR_EVENT_TYPES,
                        )
                    },
                },
                ready=lambda: True,
            )

        stage = "construct_service_host"
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=service_identity,
                scope=WireScope(execution_domain_ref),
                scope_ref=config.scope_ref,
                scope_version="arb06-cerebro-monitor-root-scope-v1",
                security_ref=_MONITOR_INGRESS_SECURITY_REF,
                security_version="arb06-cerebro-monitor-curve-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="arb06-cerebro-monitor-registration-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="arb06-cerebro-monitor-requirements-v1",
                curve_public_key=server_public,
                curve_secret_key=server_secret,
                principals={relay_public: _MONITOR_RELAY_PRINCIPAL},
                grants={
                    _MONITOR_RELAY_PRINCIPAL: (
                        PrincipalGrant(
                            relay_identity,
                            (
                                ResourceGrant(
                                    _MONITOR_INGRESS_INSTANCE_ID,
                                    "service.telemetry_ingress",
                                    _MONITOR_INGRESS_SCOPE_REF,
                                    scope,
                                    frozenset({"events.append"}),
                                ),
                            ),
                        ),
                    )
                },
            ),
            registry_path,
            resource_provider,
        )
        stage = "start_service_host"
        host.start()
        control.send(("ready", host.endpoint, host.state))
        stage = "serve_service_host"
        while True:
            host.serve_once(timeout_ms=25)
            if not control.poll(0):
                continue
            if control.recv() == ("close",):
                stage = "close_service_host"
                host.close()
                control.send(("closed", host.state))
                return
            raise AssertionError("unknown ARB06 Monitor ingress control command")
    except BaseException as error:
        error_type = type(error).__name__
        error_code = getattr(error, "code", None)
        if type(error_code) is not str or not error_code.isascii() or len(error_code) > 96:
            error_code = None
        with suppress(Exception):
            control.send(("error", stage, error_type, error_code))
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        raise
    finally:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        control.close()


def _monitor_query_host_entry(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    outbox_path: str,
    server_public: bytes,
    server_secret: bytes,
    strategy_client_public: bytes,
    strategy_principal: str,
    strategy_ref: str,
    portfolio_ref: str,
    execution_domain_ref: str,
) -> None:
    """Run the authenticated read-only Monitor component behind ServiceHost."""

    stage = "parse_service_config"
    host = None
    try:
        config = parse_service_config(raw_config)
        stage = "open_read_only_outbox"
        outbox = DurableOutbox(outbox_path, read_only=True)
        scope = WireScope(
            execution_domain_ref,
            strategy_ref=strategy_ref,
            portfolio_ref=portfolio_ref,
        )
        service_identity = WireIdentity(
            WireRole.SERVICE,
            p5a._MONITOR_PRINCIPAL,
            p5a._MONITOR_SERVICE_ID,
        )
        strategy_identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            strategy_principal,
            strategy_ref,
        )

        def resource_provider(component, instance_id, _options, _host_scope):
            if component != "monitor" or instance_id != p5a._MONITOR_INSTANCE:
                raise AssertionError("unexpected ARB06 Monitor query resource request")
            return ComponentResources.borrowed(
                {
                    "outbox": outbox,
                    "targets": {
                        scope: MonitorReadTarget(
                            _MONITOR_OUTBOX_SCOPE,
                            _MONITOR_EVENT_TYPES,
                        )
                    },
                },
                ready=lambda: True,
            )

        stage = "construct_service_host"
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=service_identity,
                scope=WireScope(execution_domain_ref),
                scope_ref=config.scope_ref,
                scope_version="v3-group-monitor-scope-v1",
                security_ref=p5a._MONITOR_SERVER_SECURITY_REF,
                security_version="v3-group-monitor-curve-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="v3-group-monitor-registration",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="v3-group-monitor-requirements",
                curve_public_key=server_public,
                curve_secret_key=server_secret,
                principals={strategy_client_public: strategy_principal},
                grants={
                    strategy_principal: (
                        PrincipalGrant(
                            strategy_identity,
                            (
                                ResourceGrant(
                                    p5a._MONITOR_INSTANCE,
                                    "service.monitor_query",
                                    p5a._MONITOR_SCOPE_REF,
                                    scope,
                                    frozenset({"monitor.read_after"}),
                                ),
                            ),
                        ),
                    )
                },
            ),
            registry_path,
            resource_provider,
        )
        stage = "start_service_host"
        host.start()
        control.send(("ready", host.endpoint, host.state))
        stage = "serve_service_host"
        while True:
            host.serve_once(timeout_ms=15)
            if not control.poll(0):
                continue
            if control.recv() == "close":
                stage = "close_service_host"
                host.close()
                control.send(("closed", host.state))
                return
            raise AssertionError("unknown ARB06 Monitor query control command")
    except BaseException as error:
        error_type = type(error).__name__
        error_code = getattr(error, "code", None)
        if type(error_code) is not str or not error_code.isascii() or len(error_code) > 96:
            error_code = None
        with suppress(Exception):
            control.send(("error", stage, error_type, error_code))
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        raise
    finally:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        control.close()


def _account_host_entry(control, *args) -> None:
    """Spawn-safe wrapper that uses the fixed R249 SDK provider fixture."""

    p5a._load_sdk_host_fixture()
    fixture = _load_fixed_partial_group_fixture()
    fixture._account_host_process(control, *args)


def _coordinator_host_entry(control, *args) -> None:
    """Spawn-safe wrapper that uses the fixed R249 SDK coordinator fixture."""

    p5a._load_sdk_host_fixture()
    fixture = _load_fixed_partial_group_fixture()
    fixture._coordinator_host_process(control, *args)


def _install_monitor_route(
    monkeypatch,
    fixture,
    *,
    monitor_server_public: bytes,
    monitor_query_endpoint: str,
) -> None:
    """Add the explicit read-only Monitor binding to the SDK group runtime."""

    original_config_builder = fixture._strategy_client_config

    def _strategy_client_config(endpoint: str, security_ref: str):
        raw = original_config_builder(endpoint, security_ref)
        return p5a._with_monitor_route(raw, fixture, monitor_query_endpoint)

    original_runtime = fixture.ServiceClientRuntime
    original_factory = fixture.ZmqTransportFactory
    monitor_identity = WireIdentity(
        WireRole.SERVICE,
        p5a._MONITOR_PRINCIPAL,
        p5a._MONITOR_SERVICE_ID,
    )

    class _MonitorEnabledRuntime(original_runtime):
        def start(self):
            receipt = super().start()
            actual = tuple(self.bindings)
            assert {binding.mount for binding in actual} == {
                "broker.order_groups",
                "broker.group_monitor",
            }
            # The accepted SDK group fixture predates the independently
            # authorized Monitor binding and asserts a one-binding startup
            # summary. Keep its group-only setup check intact; the integration
            # test separately verifies both actual runtime registrations.
            return replace(
                receipt,
                bindings=tuple(
                    binding for binding in receipt.bindings
                    if binding.mount == "broker.order_groups"
                ),
            )

        def __init__(self, *args, **kwargs):
            original_scope_resolver = kwargs["scope_resolver"]
            original_peer_resolver = kwargs["peer_resolver"]

            def _resolve_scope(scope_ref: str):
                if scope_ref == p5a._MONITOR_SCOPE_REF:
                    group_scope = original_scope_resolver(fixture._COORDINATOR_SCOPE_REF)
                    return WireScope(
                        group_scope.execution_domain_ref,
                        strategy_ref=group_scope.strategy_ref,
                        portfolio_ref=group_scope.portfolio_ref,
                    )
                return original_scope_resolver(scope_ref)

            def _resolve_peer(service_id: str):
                if service_id == p5a._MONITOR_SERVICE_ID:
                    return monitor_identity
                return original_peer_resolver(service_id)

            requested = dict(kwargs.get("requested_operations") or {})
            requested["broker.group_monitor"] = frozenset({"monitor.read_after"})
            kwargs["requested_operations"] = requested
            kwargs["scope_resolver"] = _resolve_scope
            kwargs["peer_resolver"] = _resolve_peer
            super().__init__(*args, **kwargs)

    class _MonitorAwareTransportFactory(original_factory):
        def __init__(self, security_profiles):
            copied = dict(security_profiles)
            group_keys = copied["strategy-client-security-v1"]
            copied[p5a._MONITOR_CLIENT_SECURITY_REF] = ClientCurveKeys(
                server_key=monitor_server_public,
                public_key=group_keys.public_key,
                secret_key=group_keys.secret_key,
            )
            super().__init__(copied)

    monkeypatch.setattr(fixture, "_strategy_client_config", _strategy_client_config)
    monkeypatch.setattr(fixture, "ServiceClientRuntime", _MonitorEnabledRuntime)
    monkeypatch.setattr(fixture, "ZmqTransportFactory", _MonitorAwareTransportFactory)
    monkeypatch.setattr(fixture, "_account_host_process", _account_host_entry)
    monkeypatch.setattr(fixture, "_coordinator_host_process", _coordinator_host_entry)


def _relay_service_config(endpoint: str):
    """Build the fixed, service-role Monitor ingress client configuration."""

    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": _MONITOR_RELAY_ID,
            "scope_ref": _MONITOR_RELAY_SCOPE_REF,
            "transport_ref": "arb06-cerebro-relay-unused-listener-v1",
            "registration_policy_ref": "arb06-cerebro-relay-policy-v1",
            "service_requirements_ref": "arb06-cerebro-relay-requirements-v1",
            "components": {
                "monitor": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": "arb06-cerebro-relay-unused-monitor",
                        "bind_ports": ["service.telemetry_ingress"],
                        "options": {
                            "role": "durable_ingress",
                            **_MONITOR_INGRESS_LIMITS,
                        },
                    },
                }
            },
            "clients": {
                "monitor": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "upstream.telemetry",
                                "service_id": _MONITOR_INGRESS_SERVICE_ID,
                                "instance_id": _MONITOR_INGRESS_INSTANCE_ID,
                                "scope_ref": _MONITOR_INGRESS_SCOPE_REF,
                                "transport_ref": "arb06-cerebro-relay-connect-v1",
                            }
                        ],
                        "options": {
                            "request_timeout_ms": _MONITOR_REQUEST_TIMEOUT_MS,
                            "heartbeat_interval_seconds": 5,
                        },
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "arb06-cerebro-relay-unused-listener-v1": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": _endpoint()},
                        "security_profile_ref": "arb06-cerebro-relay-unused-server-v1",
                        "options": {
                            "high_water_mark": 32,
                            "max_message_bytes": _MONITOR_MAX_MESSAGE_BYTES,
                        },
                    },
                    "arb06-cerebro-relay-connect-v1": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": _MONITOR_RELAY_SECURITY_REF,
                        "options": {
                            "request_timeout_ms": _MONITOR_REQUEST_TIMEOUT_MS,
                            "high_water_mark": 32,
                            "max_message_bytes": _MONITOR_MAX_MESSAGE_BYTES,
                        },
                    },
                },
            },
        }
    )


def _relay_group_residual(
    *,
    endpoint: str,
    group_store_path: str,
    checkpoint_path: str,
    execution_domain_ref: str,
    account_refs: tuple[str, ...],
    strategy_ref: str,
    portfolio_ref: str,
    server_public: bytes,
    relay_public: bytes,
    relay_secret: bytes,
):
    config = _relay_service_config(endpoint)
    if not group_monitor_relay_configured(config, scope_ref=_MONITOR_INGRESS_SCOPE_REF):
        raise AssertionError("relay client config is not the fixed upstream binding")
    monitor_identity = WireIdentity(
        WireRole.SERVICE,
        _MONITOR_INGRESS_PRINCIPAL,
        _MONITOR_INGRESS_SERVICE_ID,
    )
    runtime = ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.SERVICE, _MONITOR_RELAY_PRINCIPAL, _MONITOR_RELAY_ID),
        scope_resolver=lambda _scope_ref: WireScope(
            execution_domain_ref,
            account_ref=account_refs[0],
            strategy_ref=strategy_ref,
            portfolio_ref=portfolio_ref,
        ),
        peer_resolver=lambda _service_id: monitor_identity,
        transport_factory=ZmqTransportFactory(
            {
                _MONITOR_RELAY_SECURITY_REF: ClientCurveKeys(
                    server_key=server_public,
                    public_key=relay_public,
                    secret_key=relay_secret,
                )
            }
        ),
        requested_operations={"upstream.telemetry": frozenset({"events.append"})},
    )
    reader = None
    relay = None
    primary_error = None
    try:
        receipt = runtime.start()
        assert receipt.degraded_count == 0
        assert runtime.state == "registered"
        reader = SqliteGroupResidualReader(group_store_path)
        assert reader.schema_version == 2
        page = reader.read_residual_page(after_sequence=0, limit=32)
        assert len(page.events) == 1
        source_event = page.events[0]
        assert source_event.strategy_id == strategy_ref
        assert source_event.portfolio_ref == portfolio_ref
        assert source_event.account_refs == account_refs
        assert source_event.state == "RECOVERY_REQUIRED"
        assert source_event.reason == "hedge_residual_unresolved"
        assert Decimal(source_event.residual_base_units) == Decimal("3")

        relay = ServiceGroupMonitorRelay(
            runtime,
            reader,
            scope_ref=_MONITOR_INGRESS_SCOPE_REF,
            checkpoint_path=checkpoint_path,
        )
        result = relay.poll(limit=32)
        checkpoint = relay.checkpoint()
        assert result.residual_delivered == 1
        assert result.remote_delivered == 1
        assert result.checkpointed == 1
        assert result.total_delivered == 1
        assert checkpoint.sequence == source_event.sequence
        assert checkpoint.source_event_id == source_event.event_sha256
        return source_event, checkpoint
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors = []
        for resource, close in (
            (relay, None if relay is None else relay.close),
            (reader, None if reader is None else reader.close),
        ):
            if close is None:
                continue
            try:
                close()
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if runtime.state not in {"closed", "failed", "close_failed"}:
            try:
                runtime.close()
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if runtime.state != "closed" or runtime.cleanup_failures or runtime.unregister_uncertainties:
            cleanup_errors.append("RUNTIME_CLOSE_UNCERTAIN")
        if cleanup_errors:
            message = "relay cleanup failed: " + ",".join(cleanup_errors)
            if primary_error is None:
                raise AssertionError(message)
            if hasattr(primary_error, "add_note"):
                primary_error.add_note(message)


def _receive(control, *, timeout: float = 25.0):
    if not control.poll(timeout):
        raise TimeoutError("ARB06 local ServiceHost missed its bounded response")
    message = control.recv()
    if not message or message[0] == "error":
        raise AssertionError(f"ARB06 local ServiceHost failed: {message!r}")
    return message


def _close_host(process, control, *, close_command: object) -> tuple[Any, ...]:
    if process is None or control is None:
        return ()
    control.send(close_command)
    message = _receive(control)
    assert message[0] == "closed", message
    process.join(timeout=20.0)
    assert not process.is_alive(), "normal Host close did not exit within its bound"
    assert process.exitcode == 0, process.exitcode
    control.close()
    process.close()
    return message


def _primary_runtime_and_store(tmp_path: Path):
    outbox_path = tmp_path / "primary-monitor-outbox.sqlite3"
    outbox = DurableOutbox(outbox_path)
    readonly = DurableOutbox(outbox_path, read_only=True)
    primary_monitor = p5a_local.MonitorReadService(
        readonly,
        {
            WireScope(
                p5a_local._DOMAIN,
                strategy_ref=p5a_local._STRATEGY_A,
                portfolio_ref=p5a_local._PORTFOLIO,
            ): MonitorReadTarget(
                p5a_local._RESIDUAL_SCOPE,
                (_MONITOR_EVENT_TYPE,),
            )
        },
    )
    primary_registry, _coordinator, _writes, _group_scope, _monitor_scope, order_scope, query_scope = (
        p5a_local._registry(
            tmp_path,
            p5a_local._intent(),
            p5a_local._SyntheticProviderLeaf(),
            outbox,
            primary_monitor,
        )
    )
    primary_runtime = p5a_local._client_runtime(
        primary_registry,
        strategy_ref=p5a_local._STRATEGY_B,
        principal_ref=p5a_local._PRINCIPAL_B,
        bindings=(
            {
                "mount": "broker.orders",
                "service_id": p5a_local._SERVICE_ID,
                "instance_id": p5a_local._BROKER_INSTANCE,
                "scope_ref": p5a_local._ORDER_SCOPE_REF,
                "account_ref": p5a_local._ACCOUNT,
                "transport_ref": "execution-rpc",
            },
            {
                "mount": "broker.order_query",
                "service_id": p5a_local._SERVICE_ID,
                "instance_id": p5a_local._BROKER_INSTANCE,
                "scope_ref": p5a_local._QUERY_SCOPE_REF,
                "account_ref": p5a_local._ACCOUNT,
                "transport_ref": "execution-rpc",
            },
        ),
        scopes={
            p5a_local._ORDER_SCOPE_REF: order_scope,
            p5a_local._QUERY_SCOPE_REF: query_scope,
        },
        requested={
            "broker.orders": p5a_local._WRITER_OPERATIONS,
            "broker.order_query": p5a_local._QUERY_OPERATIONS,
        },
    )
    store = make_store(
        api=FakeBtApiClient(
            balance={"cash": 10_000.0, "value": 10_200.0},
            positions=[{"instrument": "BTC/USDT", "volume": 0.0, "price": 0.0}],
            open_orders=[],
        ),
        provider="btapi",
    )
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3_600.0,
        positions_refresh_interval=3_600.0,
        open_orders_refresh_interval=3_600.0,
    )
    return primary_registry, primary_runtime, store, broker


class _ResidualMonitorStrategy(bt.Strategy):
    params = (
        ("strategy_ref", "strategy-group-partial-fill"),
        ("portfolio_ref", "portfolio-group-partial-fill"),
    )

    def start(self):
        self.bind_service_execution_group()
        position = self.broker.getposition(self.data)
        self.before = (self.broker.getcash(), self.broker.getvalue(), position.size)

    def next(self):
        self.first_page = self.read_group_residuals(limit=32)
        self.replay_page = self.read_group_residuals(self.first_page.cursor, limit=32)
        position = self.broker.getposition(self.data)
        self.after = (self.broker.getcash(), self.broker.getvalue(), position.size)


def _cerebro(broker):
    frame = pandas.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=[dt.datetime(2026, 10, 17)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="BTC/USDT")
    cerebro.addstrategy(_ResidualMonitorStrategy)
    return cerebro


def test_arb06_normal_cerebro_reads_group_residual_from_real_monitor_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A real SDK recovery residual reaches the bound Strategy without booking it."""

    p5a._load_sdk_host_fixture()
    fixture = _load_fixed_partial_group_fixture()
    monitor_query_endpoint = _endpoint()
    monitor_ingress_endpoint = _endpoint()
    query_server_public, query_server_secret = zmq.curve_keypair()
    ingress_server_public, ingress_server_secret = zmq.curve_keypair()
    relay_public, relay_secret = zmq.curve_keypair()
    _install_monitor_route(
        monkeypatch,
        fixture,
        monitor_server_public=query_server_public,
        monitor_query_endpoint=monitor_query_endpoint,
    )

    cluster = fixture._GroupCluster(
        tmp_path,
        accounts=fixture._ARB03_ACCOUNTS,
        instruments=dict.fromkeys(fixture._ARB03_ACCOUNTS, (fixture._V2_INSTRUMENT,)),
        initial_states={"account-a": ("cancelled:1.5",), "account-b": ("rejected",)},
        expected_orders={
            "account-a": ((fixture._V2_INSTRUMENT, "2", "100", "buy-limit"),),
            "account-b": ((fixture._V2_INSTRUMENT, "3", "100", "sell-limit"),),
        },
        rule_specs={
            "account-a": {fixture._V2_INSTRUMENT: "2"},
            "account-b": {fixture._V2_INSTRUMENT: "1"},
        },
    )
    monitor_outbox_path = tmp_path / "arb06-monitor-outbox.sqlite3"
    DurableOutbox(monitor_outbox_path)
    query_raw = p5a._monitor_service_config(monitor_query_endpoint)
    ingress_raw = _monitor_ingress_service_config(monitor_ingress_endpoint)
    context = multiprocessing.get_context("spawn")
    query_process = query_control = ingress_process = ingress_control = None
    primary_registry = primary_runtime = store = None
    primary_error = None

    try:
        query_process, query_control = p5a._start_process(
            context,
            name="arb06-cerebro-monitor-query-host",
            target=_monitor_query_host_entry,
            args=(
                query_raw,
                str(tmp_path / "arb06-monitor-query-registry.sqlite3"),
                str(monitor_outbox_path),
                query_server_public,
                query_server_secret,
                cluster.strategy_client_public,
                fixture._STRATEGY_PRINCIPAL,
                fixture._STRATEGY,
                fixture._PORTFOLIO,
                fixture._DOMAIN,
            ),
        )
        query_ready = _receive(query_control)
        assert query_ready[0] == "ready" and query_ready[1] == monitor_query_endpoint

        ingress_process, ingress_control = p5a._start_process(
            context,
            name="arb06-cerebro-monitor-ingress-host",
            target=_monitor_ingress_host_entry,
            args=(
                ingress_raw,
                str(tmp_path / "arb06-monitor-ingress-registry.sqlite3"),
                str(monitor_outbox_path),
                ingress_server_public,
                ingress_server_secret,
                relay_public,
                fixture._DOMAIN,
                fixture._STRATEGY,
                fixture._PORTFOLIO,
            ),
        )
        ingress_ready = _receive(ingress_control)
        assert ingress_ready[0] == "ready" and ingress_ready[1] == monitor_ingress_endpoint

        with cluster:
            assert {binding.mount for binding in cluster.strategy_runtime.bindings} == {
                "broker.order_groups",
                "broker.group_monitor",
            }
            snapshot = cluster.submit_group(
                fixture._group_request(
                    fixture._GROUP_ARB03,
                    cluster.metadata_reference_ns,
                    (
                        (
                            "leg-a",
                            "account-a",
                            Side.BUY,
                            Decimal("2"),
                            fixture._V2_INSTRUMENT,
                        ),
                        (
                            "leg-b",
                            "account-b",
                            Side.SELL,
                            Decimal("4"),
                            fixture._V2_INSTRUMENT,
                        ),
                    ),
                )
            )
            assert snapshot.state is GroupOrderState.RECOVERY_REQUIRED
            assert snapshot.error_code == "hedge_residual_unresolved"
            assert snapshot.residual_base_units == Decimal("3")
            assert snapshot.request.strategy_id == fixture._STRATEGY
            assert snapshot.request.portfolio_ref == fixture._PORTFOLIO
            assert snapshot.request.account_refs == fixture._ARB03_ACCOUNTS

            group_store_path = cluster.coordinator_paths["groups"]
            source_event, checkpoint = _relay_group_residual(
                endpoint=monitor_ingress_endpoint,
                group_store_path=group_store_path,
                checkpoint_path=str(tmp_path / "arb06-monitor-relay-checkpoint.sqlite3"),
                execution_domain_ref=fixture._DOMAIN,
                account_refs=fixture._ARB03_ACCOUNTS,
                strategy_ref=fixture._STRATEGY,
                portfolio_ref=fixture._PORTFOLIO,
                server_public=ingress_server_public,
                relay_public=relay_public,
                relay_secret=relay_secret,
            )
            assert checkpoint.sequence == source_event.sequence

            monitor_outbox = DurableOutbox(monitor_outbox_path, read_only=True)
            durable_rows, has_more = monitor_outbox.read_page_types(
                _MONITOR_OUTBOX_SCOPE,
                _MONITOR_EVENT_TYPES,
                0,
                10,
            )
            assert has_more is False
            assert len(durable_rows) == 1
            durable_event = durable_rows[0].event
            assert durable_event.event_type == _MONITOR_EVENT_TYPE
            assert durable_event.scope == _MONITOR_OUTBOX_SCOPE
            assert set(durable_event.data) == {"producer", "source_event_id", "payload"}
            assert durable_event.data["producer"] == {
                "role": "service",
                "principal_ref": _MONITOR_RELAY_PRINCIPAL,
                "actor_ref": _MONITOR_RELAY_ID,
                "delegate_ref": None,
            }
            assert durable_event.data["source_event_id"] == _projected_residual_event_id(
                durable_event.data["payload"]
            )
            assert durable_event.event_id.startswith("service-event:")
            assert durable_event.event_id != durable_event.data["source_event_id"]
            assert durable_event.data["payload"]["state"] == "RECOVERY_REQUIRED"
            assert durable_event.data["payload"]["reason"] == "hedge_residual_unresolved"
            assert Decimal(durable_event.data["payload"]["residual_base_units"]) == Decimal("3")
            assert durable_event.data["payload"]["source_sequence"] == source_event.sequence
            assert durable_event.data["payload"]["group_id"] == fixture._GROUP_ARB03
            assert durable_event.data["payload"]["strategy_id"] == fixture._STRATEGY
            assert durable_event.data["payload"]["account_refs"] == fixture._ARB03_ACCOUNTS

            primary_registry, primary_runtime, store, broker = _primary_runtime_and_store(
                tmp_path
            )
            route = ServiceStrategyGroupRoute(
                strategy_ref=fixture._STRATEGY,
                portfolio_ref=fixture._PORTFOLIO,
                account_refs=fixture._ARB03_ACCOUNTS,
                runtime=cluster.strategy_runtime,
                group_scope_ref=fixture._COORDINATOR_SCOPE_REF,
                monitor_scope_ref=p5a._MONITOR_SCOPE_REF,
                owned=False,
                monitor_producer_principal_ref=_MONITOR_RELAY_PRINCIPAL,
                monitor_producer_actor_ref=_MONITOR_RELAY_ID,
            )
            session = ServiceExecutionSession(
                primary_runtime,
                mount="broker.orders",
                scope_ref=p5a_local._ORDER_SCOPE_REF,
                query_mount="broker.order_query",
                query_scope_ref=p5a_local._QUERY_SCOPE_REF,
                strategy_group_routes=(route,),
            )
            strategies = session.run(_cerebro(broker))
            assert session.state == "closed"
            assert session.cleanup_report.errors == ()
            assert session.cleanup_report.store_connected is False
            assert session.cleanup_report.runtime_state == "closed"
            assert primary_runtime.state == "closed"
            assert len(strategies) == 1
            strategy = strategies[0]
            assert len(strategy.first_page.events) == 1
            residual = strategy.first_page.events[0]
            assert residual.sequence == durable_rows[0].sequence
            assert residual.event_id == durable_event.event_id
            assert residual.journal_generation == source_event.journal_generation
            assert residual.source_revision == source_event.revision
            assert residual.source_created_at_ns == source_event.created_at_ns
            assert residual.portfolio_ref == fixture._PORTFOLIO
            assert residual.group_id == fixture._GROUP_ARB03
            assert residual.strategy_ref == fixture._STRATEGY
            assert residual.account_refs == fixture._ARB03_ACCOUNTS
            assert residual.state == "RECOVERY_REQUIRED"
            assert residual.reason == "hedge_residual_unresolved"
            assert Decimal(residual.residual_base_units) == Decimal("3")
            assert residual.first_leg_id == "leg-a"
            assert residual.second_leg_id == "leg-b"
            assert Decimal(residual.first_filled_quantity) == Decimal("1.5")
            assert Decimal(residual.second_filled_quantity) == Decimal("0")
            assert strategy.first_page.has_more is False
            assert strategy.first_page.cursor.sequence == residual.sequence
            assert strategy.first_page.cursor.event_id == residual.event_id
            assert strategy.first_page.cursor.journal_generation == residual.journal_generation
            assert strategy.replay_page.events == ()
            assert strategy.replay_page.cursor == strategy.first_page.cursor
            assert strategy.before == strategy.after
            assert strategy.before[0] == 10_000.0
            assert strategy.before[1] == 10_200.0
            assert strategy.before[2] == 0.0
            assert cluster.strategy_runtime.state == "registered"
            assert cluster.strategy_runtime.cleanup_failures == 0
            assert cluster.strategy_runtime.unregister_uncertainties == 0
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors = []
        for process, control, close_command in (
            (ingress_process, ingress_control, ("close",)),
            (query_process, query_control, "close"),
        ):
            if process is None or control is None:
                continue
            try:
                _close_host(process, control, close_command=close_command)
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if primary_runtime is not None and primary_runtime.state not in {
            "closed",
            "failed",
            "close_failed",
        }:
            try:
                primary_runtime.close()
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if store is not None and store.is_connected:
            try:
                store.stop()
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if primary_registry is not None:
            try:
                primary_registry.close()
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            message = "ARB06 cleanup failed: " + ",".join(cleanup_errors)
            if primary_error is None:
                raise AssertionError(message)
            if hasattr(primary_error, "add_note"):
                primary_error.add_note(message)
