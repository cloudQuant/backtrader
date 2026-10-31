"""Real local service-host integration for the read-only Store proxy."""

from __future__ import annotations

import io
import multiprocessing
import socket
import threading
import time
from contextlib import suppress
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import backtrader as bt
import zmq
import pytest
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountOpenOrder,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_history_protocol import (
    MarketBar,
    MarketHistoryPage,
    MarketHistoryRequest,
)
from bt_api_base.market_protocol import (
    MarketInstrumentKey,
    MarketSourceDescriptor,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway import GatewayCommandKind, GatewayEventJournal, GatewayPrincipal
from bt_api_gateway.account_session_worker import GatewayAccountSessionWorker
from bt_api_gateway.market_hub import GatewayMarketHub
from bt_api_gateway.service_component import GatewayServiceAccountScope
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.service_account import ServiceAccountClient
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_market import ServiceMarketClient, ZmqMarketTransportFactory
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
from bt_api_run_contract import Environment, ReferencesV2, TrustedRouteV2
from bt_api_runtime import (
    SdkClockBinding,
    SdkEnvironmentMapping,
    SdkMarketSourceExpectation,
    SdkReadOnlyFacadeFactory,
    SdkReadOnlySpecV2,
    SdkReadOnlyTargetsV2,
    SdkReadOnlyTargetV2,
    SdkRouteReference,
    SdkRouteReferencesV2,
)
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore
from backtrader.stores.service_read_proxy import (
    SERVICE_ORDERBOOK_SCHEMA_VERSION,
    ServiceFeedBinding,
    ServiceOrderBookBinding,
    ServiceReadProxy,
)

_DOMAIN_REF = "paper:read-proxy-integration"
_STRATEGY_REF = "strategy-read-proxy-integration"
_CLIENT_PRINCIPAL = "principal-read-proxy-integration"
_ACCOUNT_SERVICE_ID = "synthetic-account-read-service"
_ACCOUNT_INSTANCE_ID = "gateway-account-read"
_ACCOUNT_SCOPE_REF = "synthetic-account-scope-v1"
_ACCOUNT_TRANSPORT_REF = "account-listener-v1"
_ACCOUNT_CLIENT_TRANSPORT_REF = "account-client-v1"
_ACCOUNT_SECURITY_REF = "account-curve-v1"
_ACCOUNT_REF = "synthetic-account"
_JOURNAL_SCOPE = "journal:synthetic-account"
_STATE_SCOPE = "state:synthetic-account"
_MARKET_SERVICE_ID = "synthetic-market-history-service"
_MARKET_INSTANCE_ID = "gateway-market-history"
_MARKET_SCOPE_REF = "synthetic-market-scope-v1"
_MARKET_TRANSPORT_REF = "market-listener-v1"
_MARKET_CLIENT_TRANSPORT_REF = "market-client-v1"
_MARKET_SECURITY_REF = "market-curve-v1"
_REQUEST_TIMEOUT_MS = 1_500
_HEARTBEAT_SECONDS = 5
_A2_HEARTBEAT_SECONDS = 300
_MAX_MESSAGE_BYTES = 262_144
_SYMBOL = "SYNTH-USD"
_ACCOUNT_KEY = AccountKey("synthetic", "loopback", "paper", "read-proxy-owner")
_RESOURCE = AccountResourceKey("spot", "cash")
_INSTRUMENT = MarketInstrumentKey(
    provider="synthetic",
    venue="loopback",
    environment="paper",
    product_type="spot",
    instrument_id="synthetic-spot-1",
    native_symbol=_SYMBOL,
)
_MARKET_KEY = MarketSubscriptionKey(
    source_ref="synthetic-history-source",
    entitlement_ref="synthetic-history-entitlement",
    instrument=_INSTRUMENT,
    channel="bar",
    timeframe="1m",
)
_ORDERBOOK_KEY = MarketSubscriptionKey(
    source_ref="synthetic-orderbook-source",
    entitlement_ref="synthetic-orderbook-entitlement",
    instrument=_INSTRUMENT,
    channel="orderbook",
    depth=2,
)
_ACCOUNT_OPERATIONS = frozenset({"account.snapshot"})
_ACCOUNT_HOST_OPERATIONS = frozenset(
    {
        "account.ack",
        "account.configuration",
        "account.head",
        "account.progress",
        "account.read_after",
        "account.server_time_probe",
        "account.snapshot",
    }
)
_MARKET_OPERATIONS = frozenset(
    {
        "market.subscribe",
        "market.unsubscribe",
        "market.snapshot",
        "market.head",
        "market.read_after",
        "market.history",
    }
)
# Host-advertised operations differ from the six operations V2 requests.
_MARKET_HOST_OPERATIONS = _MARKET_OPERATIONS | frozenset({"market.bootstrap_many"})
_HISTORY_START = "2020-01-01T00:07:00Z"
_HISTORY_END = "2020-01-01T00:10:00Z"
_PROXY_CLOCK = datetime(2020, 1, 1, 0, 12, tzinfo=UTC)
_HISTORY_BARS = (
    MarketBar(
        "2020-01-01T00:08:00Z",
        "2020-01-01T00:09:00Z",
        "100",
        "101",
        "99",
        "100.5",
        "3",
    ),
    MarketBar(
        "2020-01-01T00:09:00Z",
        "2020-01-01T00:10:00Z",
        "100.5",
        "102",
        "100",
        "101.5",
        "4",
    ),
)
_LIVE_BARS = (
    _HISTORY_BARS[1],
    MarketBar(
        "2020-01-01T00:10:00Z",
        "2020-01-01T00:11:00Z",
        "101.5",
        "103",
        "101",
        "102.5",
        "5",
    ),
)


def _free_endpoints(count: int) -> tuple[str, ...]:
    probes: list[socket.socket] = []
    try:
        endpoints = []
        for _ in range(count):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            probes.append(probe)
            endpoints.append(f"tcp://127.0.0.1:{probe.getsockname()[1]}")
        return tuple(endpoints)
    finally:
        for probe in probes:
            probe.close()


def _service_config(
    *,
    service_id: str,
    scope_ref: str,
    transport_ref: str,
    instance_id: str,
    bind_ports: list[str],
    options: dict[str, Any],
    rpc_bind: str,
    security_ref: str,
    market_bind: str | None = None,
) -> dict[str, Any]:
    endpoints = {"rpc_bind": rpc_bind}
    if market_bind is not None:
        endpoints["market_bind"] = market_bind
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": service_id,
        "scope_ref": scope_ref,
        "transport_ref": transport_ref,
        "registration_policy_ref": f"policy:{service_id}:v1",
        "service_requirements_ref": f"requirements:{service_id}:v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": instance_id,
                    "bind_ports": bind_ports,
                    "options": options,
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                transport_ref: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": endpoints,
                    "security_profile_ref": security_ref,
                    "options": {
                        "high_water_mark": 64,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _client_config(account_rpc: str, market_rpc: str, market_pub: str) -> dict[str, Any]:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY_REF},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "store.account",
                            "service_id": _ACCOUNT_SERVICE_ID,
                            "instance_id": _ACCOUNT_INSTANCE_ID,
                            "scope_ref": _ACCOUNT_SCOPE_REF,
                            "account_ref": _ACCOUNT_REF,
                            "transport_ref": _ACCOUNT_CLIENT_TRANSPORT_REF,
                        },
                        {
                            "mount": "store.market",
                            "service_id": _MARKET_SERVICE_ID,
                            "instance_id": _MARKET_INSTANCE_ID,
                            "scope_ref": _MARKET_SCOPE_REF,
                            "transport_ref": _MARKET_CLIENT_TRANSPORT_REF,
                        },
                    ],
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "heartbeat_interval_seconds": _HEARTBEAT_SECONDS,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _ACCOUNT_CLIENT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": account_rpc},
                    "security_profile_ref": _ACCOUNT_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "high_water_mark": 64,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                },
                _MARKET_CLIENT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {
                        "rpc_connect": market_rpc,
                        "market_connect": market_pub,
                    },
                    "security_profile_ref": _MARKET_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "high_water_mark": 64,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                },
            },
        },
    }


class _SyntheticAccountProvider:
    """A local full-read session with no order or account mutation methods."""

    def __init__(self) -> None:
        self.connect_calls = 0
        self.read_calls = 0
        self.close_calls = 0
        self.generation: str | None = None

    def connect(self, *, account_key: AccountKey, generation: str, timeout: float) -> None:
        if account_key != _ACCOUNT_KEY or not generation or timeout <= 0 or self.generation:
            raise AssertionError("invalid synthetic account session")
        self.connect_calls += 1
        self.generation = generation

    def read_account(self, *, generation: str, timeout: float) -> AccountObservation:
        if generation != self.generation or timeout <= 0:
            raise AssertionError("account read used an inactive synthetic generation")
        self.read_calls += 1
        return _account_observation(self.read_calls)

    def close(self) -> bool:
        self.close_calls += 1
        self.generation = None
        return True


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _account_observation(sequence: int) -> AccountObservation:
    observed_at = _utc_now()
    open_orders = (
        (
            AccountOpenOrder(
                resource=_RESOURCE,
                instrument=_INSTRUMENT,
                order_id="synthetic-open-order-1",
                side="buy",
                position_side="net",
                order_type="limit",
                status="open",
                quantity="1",
                filled_quantity="0",
                qty_unit="unit",
                created_at_utc=observed_at,
                observed_at_utc=observed_at,
                client_order_id="synthetic-client-order-1",
                limit_price="9.5",
                price_currency="USD",
                reduce_only=False,
            ),
        )
        if sequence == 1
        else ()
    )
    return AccountObservation(
        account_key=_ACCOUNT_KEY,
        observation_id=f"synthetic-observation-{sequence}",
        coverage=(_RESOURCE,),
        balances=(
            AccountBalance(
                resource=_RESOURCE,
                currency="USD",
                total="105",
                available="80",
                locked="25",
                observed_at_utc=observed_at,
            ),
        ),
        positions=(
            AccountPosition(
                resource=_RESOURCE,
                instrument=_INSTRUMENT,
                side="net",
                quantity="2.5",
                qty_unit="unit",
                average_price="10",
                price_currency="USD",
                observed_at_utc=observed_at,
            ),
        ),
        valuation=AccountValuation(
            currency="USD",
            available_cash="80",
            equity="105",
            observed_at_utc=observed_at,
        ),
        started_at_utc=observed_at,
        completed_at_utc=observed_at,
        consistency="provider_atomic",
        balances_complete=True,
        positions_complete=True,
        open_orders=open_orders,
        open_orders_complete=True,
    )


class _SyntheticMarketProvider:
    """Count one source acquisition and publish only owner-thread fixtures."""

    def __init__(self, key: MarketSubscriptionKey = _MARKET_KEY) -> None:
        self.starts = 0
        self.stops = 0
        self.generation: str | None = None
        self.hub: GatewayMarketHub | None = None
        self.key = key

    def subscribe(self, key: MarketSubscriptionKey, *, generation: str) -> object:
        if key != self.key or not generation or self.generation is not None:
            raise AssertionError("unexpected synthetic market acquisition")
        self.starts += 1
        self.generation = generation
        return ("synthetic-stream", key.stream_id, generation)

    def unsubscribe(self, handle: object) -> bool:
        if not isinstance(handle, tuple) or handle != (
            "synthetic-stream",
            self.key.stream_id,
            self.generation,
        ):
            raise AssertionError("synthetic market release used an unknown handle")
        self.stops += 1
        self.generation = None
        return True

    def describe_source(
        self,
        handle: object,
        *,
        key: MarketSubscriptionKey,
        generation: str,
        stream_id: str,
        epoch: str,
    ) -> MarketSourceDescriptor:
        if (
            key != self.key
            or generation != self.generation
            or handle != ("synthetic-stream", key.stream_id, generation)
            or stream_id != key.stream_id
        ):
            raise AssertionError("synthetic source descriptor is not bound to its stream")
        return MarketSourceDescriptor(
            key=key,
            stream_id=stream_id,
            epoch=epoch,
            provider=key.instrument.provider,
            source="synthetic.servicehost.market",
            connection_generation=self.starts,
            clock_domain_id="synthetic-provider-clock",
            clock_source_session_id=f"synthetic-session-{self.starts}",
            clock_source="synthetic-provider-clock",
        )

    def publish(self, index: int) -> int:
        if self.hub is None or self.generation is None or type(index) is not int:
            raise AssertionError("synthetic market publisher is not ready")
        if self.key.channel == "orderbook":
            if index != 0:
                raise AssertionError("synthetic orderbook fixture has one fixed snapshot")
            data = {
                "schema_version": SERVICE_ORDERBOOK_SCHEMA_VERSION,
                "complete_state": True,
                "timestamp": datetime.now(UTC).timestamp(),
                "symbol": self.key.instrument.native_symbol,
                "exchange": self.key.instrument.venue,
                "asset_type": self.key.instrument.product_type,
                "bids": [["100", "3"], ["99.5", "2"]],
                "asks": [["100.5", "4"], ["101", "5"]],
                "sequence": 1,
                "previous_sequence": None,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "snapshot",
                "stale": False,
                "stale_reason": "",
                "recovery_snapshot": False,
            }
        else:
            if not 0 <= index < len(_LIVE_BARS):
                raise AssertionError("synthetic bar index is outside the fixed fixture")
            data = _LIVE_BARS[index].to_dict()
        event = self.hub.publish(
            self.key,
            data,
            _utc_now(),
            generation=self.generation,
        )
        return event.header.sequence


class _SyntheticMarketProviderWithPollSpy(_SyntheticMarketProvider):
    """Expose provider polling as an independent synthetic leaf counter."""

    def __init__(self, key: MarketSubscriptionKey = _MARKET_KEY) -> None:
        super().__init__(key)
        self.poll_calls = 0

    def poll(self, handle: object, *, limit: int):
        if handle != ("synthetic-stream", self.key.stream_id, self.generation):
            raise AssertionError("synthetic provider poll used an unknown handle")
        if type(limit) is not int or limit <= 0:
            raise AssertionError("synthetic provider poll limit must be positive")
        self.poll_calls += 1
        return ()


class _SyntheticHistoryProvider:
    """Return a bounded, deterministic two-bar history page."""

    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[MarketHistoryRequest] = []

    def fetch(self, request: MarketHistoryRequest, timeout_seconds: float) -> MarketHistoryPage:
        if request.key != _MARKET_KEY or timeout_seconds <= 0:
            raise AssertionError("history provider received an unexpected request")
        if request.start_time_utc != _HISTORY_START or request.end_time_utc != _HISTORY_END:
            raise AssertionError("history request escaped its fixed synthetic interval")
        self.calls += 1
        self.requests.append(request)
        return MarketHistoryPage(
            request=request,
            bars=_HISTORY_BARS,
            complete=True,
            next_start_time_utc=None,
            observed_at_utc="2020-01-01T00:12:00Z",
        )


def _account_service_process(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    journal_path: str,
    guard_directory: str,
    server_keys: tuple[bytes, bytes],
    client_key: bytes,
) -> None:
    host = None
    provider = _SyntheticAccountProvider()
    worker = None
    try:
        config = parse_service_config(raw_config)
        principal = _CLIENT_PRINCIPAL
        gateway_scope = GatewayServiceAccountScope(
            account_ref=_ACCOUNT_REF,
            execution_domain_ref=_DOMAIN_REF,
            journal_account_scope=_JOURNAL_SCOPE,
            account_read_strategy_scope=_STATE_SCOPE,
            shared_account_facts_scope=_STATE_SCOPE,
            shared_fact_strategy_refs=frozenset({_STRATEGY_REF}),
        )
        gateway_principal = GatewayPrincipal(
            principal_id=principal,
            account_scopes=frozenset({_JOURNAL_SCOPE}),
            strategy_scopes=frozenset({_STATE_SCOPE}),
            allowed_kinds=frozenset({GatewayCommandKind.READ}),
        )
        journal = GatewayEventJournal(journal_path)
        worker = GatewayAccountSessionWorker(
            provider,
            journal,
            account_key=_ACCOUNT_KEY,
            journal_account_scope=_JOURNAL_SCOPE,
            state_scope=_STATE_SCOPE,
            guard=LocalAccountSessionGuard(
                Path(guard_directory),
                _ACCOUNT_KEY.account_key_id,
                owner_ref="synthetic-account-host",
            ),
            required_coverage=(_RESOURCE,),
            require_open_orders=True,
            refresh_interval_seconds=60,
            max_staleness_seconds=120,
            request_timeout_seconds=2,
        )

        def resources(component, _instance_id, options, _scope):
            if component != "gateway" or options.get("role") != "account_session_worker":
                raise AssertionError("unexpected account service component")
            return ComponentResources.owned(
                {
                    "journal": journal,
                    "accounts": {_ACCOUNT_REF: gateway_scope},
                    "principals": {principal: gateway_principal},
                },
                ready=lambda: True,
                close=worker.close,
                internal_ports={"service.provider_session": worker},
            )

        authority = TrustedServiceAuthority(
            identity=WireIdentity(
                WireRole.SERVICE,
                "principal-account-service",
                _ACCOUNT_SERVICE_ID,
            ),
            scope=WireScope(_DOMAIN_REF),
            scope_ref=config.scope_ref,
            scope_version="account-scope-v1",
            security_ref=_ACCOUNT_SECURITY_REF,
            security_version="curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="account-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="account-requirements-v1",
            curve_public_key=server_keys[0],
            curve_secret_key=server_keys[1],
            principals={client_key: principal},
            grants={
                principal: (
                    PrincipalGrant(
                        WireIdentity(
                            WireRole.STRATEGY_CLIENT,
                            principal,
                            _STRATEGY_REF,
                        ),
                        (
                            ResourceGrant(
                                _ACCOUNT_INSTANCE_ID,
                                "service.account_read",
                                _ACCOUNT_SCOPE_REF,
                                WireScope(
                                    _DOMAIN_REF,
                                    account_ref=_ACCOUNT_REF,
                                    strategy_ref=_STRATEGY_REF,
                                ),
                                _ACCOUNT_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
        )
        host = ServiceHost(config, authority, registry_path, resources)
        host.start()
        control.send(("ready", host.endpoint, _account_status(host, worker, provider)))
        while True:
            host.serve_once(10)
            if not control.poll():
                continue
            command = control.recv()
            if command[0] == "status":
                control.send(("status", _account_status(host, worker, provider)))
            elif command[0] == "refresh":
                snapshot = worker.refresh()
                control.send(
                    (
                        "refreshed",
                        snapshot.snapshot_id,
                        snapshot.cursor,
                        _account_status(host, worker, provider),
                    )
                )
            elif command[0] == "close":
                host.close()
                control.send(("closed", _account_status(host, worker, provider)))
                return
            else:
                raise AssertionError("unknown account host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _account_status(host, worker, provider) -> dict[str, Any]:
    snapshot = worker.latest_snapshot
    writable = tuple(
        name
        for name in ("submit_order", "cancel_order", "place_order", "execute")
        if callable(getattr(provider, name, None))
    )
    return {
        "host": host.state,
        "worker": worker.state,
        "ready": worker.ready,
        "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
        "cursor": None if snapshot is None else snapshot.cursor,
        "connect_calls": provider.connect_calls,
        "read_calls": provider.read_calls,
        "close_calls": provider.close_calls,
        "provider_write_methods": writable,
    }


def _account_read_control_host_process(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    journal_path: str,
    server_keys: tuple[bytes, bytes],
    client_key: bytes,
) -> None:
    """Start a real account-read Host without a provider-session worker."""

    host = None
    journal = None
    request_operations: list[str] = []
    try:
        config = parse_service_config(raw_config)
        principal = _CLIENT_PRINCIPAL
        gateway_scope = GatewayServiceAccountScope(
            account_ref=_ACCOUNT_REF,
            execution_domain_ref=_DOMAIN_REF,
            journal_account_scope=_JOURNAL_SCOPE,
            account_read_strategy_scope=_STATE_SCOPE,
            shared_account_facts_scope=_STATE_SCOPE,
            shared_fact_strategy_refs=frozenset({_STRATEGY_REF}),
        )
        gateway_principal = GatewayPrincipal(
            principal_id=principal,
            account_scopes=frozenset({_JOURNAL_SCOPE}),
            strategy_scopes=frozenset({_STATE_SCOPE}),
            allowed_kinds=frozenset({GatewayCommandKind.READ}),
        )
        journal = GatewayEventJournal(journal_path)

        def resources(component, _instance_id, _options, _scope):
            if component != "gateway":
                raise AssertionError("unexpected account control component")
            return ComponentResources.borrowed(
                {
                    "journal": journal,
                    "accounts": {_ACCOUNT_REF: gateway_scope},
                    "principals": {principal: gateway_principal},
                },
                ready=lambda: True,
            )

        authority = TrustedServiceAuthority(
            identity=WireIdentity(
                WireRole.SERVICE,
                "principal-account-service",
                _ACCOUNT_SERVICE_ID,
            ),
            scope=WireScope(_DOMAIN_REF),
            scope_ref=config.scope_ref,
            scope_version="account-scope-v1",
            security_ref=_ACCOUNT_SECURITY_REF,
            security_version="curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="account-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="account-requirements-v1",
            curve_public_key=server_keys[0],
            curve_secret_key=server_keys[1],
            principals={client_key: principal},
            grants={
                principal: (
                    PrincipalGrant(
                        WireIdentity(
                            WireRole.STRATEGY_CLIENT,
                            principal,
                            _STRATEGY_REF,
                        ),
                        (
                            ResourceGrant(
                                _ACCOUNT_INSTANCE_ID,
                                "service.account_read",
                                _ACCOUNT_SCOPE_REF,
                                WireScope(
                                    _DOMAIN_REF,
                                    account_ref=_ACCOUNT_REF,
                                    strategy_ref=_STRATEGY_REF,
                                ),
                                _ACCOUNT_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
        )
        host = ServiceHost(config, authority, registry_path, resources)
        dispatch = host._dispatch_request

        def observe_dispatch(authenticated_principal, request):
            request_operations.append(request.header.operation)
            return dispatch(authenticated_principal, request)

        host._dispatch_request = observe_dispatch
        host.start()
        control.send(
            (
                "ready",
                host.endpoint,
                _read_control_host_status(host, request_operations),
            )
        )
        while True:
            host.serve_once(10)
            if not control.poll():
                continue
            command = control.recv()
            if command[0] == "status":
                control.send(
                    ("status", _read_control_host_status(host, request_operations))
                )
            elif command[0] == "close":
                host.close()
                control.send(
                    ("closed", _read_control_host_status(host, request_operations))
                )
                return
            else:
                raise AssertionError("unknown account control host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _read_control_host_status(host, request_operations: list[str]) -> dict[str, Any]:
    components = tuple(host.summary["components"])
    capabilities = tuple(
        sorted(
            (capability["port"], tuple(capability["operations"]))
            for component in components
            for capability in component["capabilities"]
        )
    )
    internal_ports = tuple(
        sorted(
            port
            for component in components
            for port in component["internal_ports"]
        )
    )
    return {
        "host": host.state,
        "capabilities": capabilities,
        "internal_ports": internal_ports,
        "request_operations": tuple(request_operations),
        "account_snapshot_calls": request_operations.count("account.snapshot"),
        "order_write_calls": sum(
            request_operations.count(operation)
            for operation in ("orders.submit", "orders.cancel")
        ),
        "cleanup_failures": tuple(host.summary["cleanup_failures"]),
    }


def _market_service_process(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    server_keys: tuple[bytes, bytes],
    client_key: bytes,
    market_key: MarketSubscriptionKey = _MARKET_KEY,
    observe_requests: bool = False,
) -> None:
    host = None
    provider = (
        _SyntheticMarketProviderWithPollSpy(market_key)
        if observe_requests
        else _SyntheticMarketProvider(market_key)
    )
    history = _SyntheticHistoryProvider()
    request_operations: list[str] = []
    try:
        config = parse_service_config(raw_config)
        identity = WireIdentity(
            WireRole.SERVICE,
            "principal-market-service",
            _MARKET_SERVICE_ID,
        )
        scope = WireScope(_DOMAIN_REF)
        hub = GatewayMarketHub(
            provider,
            key_universe=frozenset({market_key}),
            principal_allowed_keys={_CLIENT_PRINCIPAL: frozenset({market_key})},
            service_identity=identity,
            service_scope=scope,
            history_provider=history,
            history_timeout_seconds=2,
        )
        provider.hub = hub
        authority = TrustedServiceAuthority(
            identity=identity,
            scope=scope,
            scope_ref=config.scope_ref,
            scope_version="market-scope-v1",
            security_ref=_MARKET_SECURITY_REF,
            security_version="curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="market-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="market-requirements-v1",
            curve_public_key=server_keys[0],
            curve_secret_key=server_keys[1],
            principals={client_key: _CLIENT_PRINCIPAL},
            grants={
                _CLIENT_PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(
                            WireRole.STRATEGY_CLIENT,
                            _CLIENT_PRINCIPAL,
                            _STRATEGY_REF,
                        ),
                        (
                            ResourceGrant(
                                _MARKET_INSTANCE_ID,
                                "service.market_source",
                                _MARKET_SCOPE_REF,
                                WireScope(
                                    _DOMAIN_REF,
                                    strategy_ref=_STRATEGY_REF,
                                ),
                                _MARKET_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
        )

        def resources(component, _instance_id, _options, _scope):
            if component != "gateway":
                raise AssertionError("unexpected market service component")
            return ComponentResources.owned(
                {"hub": hub},
                ready=lambda: hub.ready,
                close=hub.close,
            )

        host = ServiceHost(config, authority, registry_path, resources)
        if observe_requests:
            dispatch = host._dispatch_request

            def observe_dispatch(authenticated_principal, request):
                request_operations.append(request.header.operation)
                return dispatch(authenticated_principal, request)

            host._dispatch_request = observe_dispatch
        host.start()
        control.send(
            (
                "ready",
                host.endpoint,
                host.market_endpoint,
                _market_status(
                    host,
                    hub,
                    provider,
                    history,
                    request_operations=request_operations,
                ),
            )
        )
        while True:
            host.serve_once(10)
            if not control.poll():
                continue
            command = control.recv()
            if command[0] == "status":
                # Refresh Host registry projection after client register/unregister.
                host.serve_once(0)
                control.send(("status", _market_status(host, hub, provider, history, request_operations=request_operations)))
            elif command[0] == "publish":
                sequence = provider.publish(command[1])
                control.send(("published", command[1], sequence))
            elif command[0] == "close":
                host.close()
                control.send(("closed", _market_status(host, hub, provider, history, request_operations=request_operations)))
                return
            else:
                raise AssertionError("unknown market host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _market_status(host, hub, provider, history, *, request_operations=None) -> dict[str, Any]:
    """Report Host lease projection separately from Hub subscription readiness.

    ``host_active_registrations`` is the last Host maintenance projection;
    ``readiness.active_registrations`` counts provider subscription refs.
    """
    market_summary = host.summary["market"]
    components = tuple(host.summary["components"])
    capabilities = tuple(
        sorted(
            (capability["port"], tuple(capability["operations"]))
            for component in components
            for capability in component["capabilities"]
        )
    )
    operations = tuple(request_operations or ())
    return {
        "capabilities": capabilities,
        "internal_ports": tuple(
            sorted(
                port
                for component in components
                for port in component["internal_ports"]
            )
        ),
        "host": host.state,
        "publisher_endpoint": market_summary["endpoint"],
        "host_active_registrations": market_summary["active_registrations"],
        "readiness": dict(hub.readiness),
        "source_starts": provider.starts,
        "provider_poll_calls": getattr(provider, "poll_calls", 0),
        "source_stops": provider.stops,
        "history_calls": history.calls,
        "source_diagnostics": dict(hub.source_diagnostics),
        "request_operations": operations,
        "market_subscribe_calls": operations.count("market.subscribe"),
        "market_unsubscribe_calls": operations.count("market.unsubscribe"),
        "cleanup_failures": tuple(host.summary["cleanup_failures"]),
    }


def _start_process(context, target, args, label: str) -> dict[str, Any]:
    parent, child = context.Pipe(duplex=True)
    try:
        process = context.Process(target=target, args=(child, *args), name=label)
    except BaseException:
        for connection in (parent, child):
            with suppress(BaseException):
                connection.close()
        raise
    record: dict[str, Any] = {
        "label": label,
        "process": process,
        "pipe": parent,
        "closed": False,
        "close_requested": False,
    }
    try:
        process.start()
    except BaseException:
        parent.close()
        child.close()
        process.close()
        raise
    child.close()
    return record


def _receive(pipe, timeout: float = 12.0):
    assert pipe.poll(timeout), "spawned service host missed its response bound"
    return pipe.recv()


def _join_publisher_bounded(publisher, cleanup_failures, *, timeout: float) -> None:
    if publisher is None or not publisher.is_alive():
        return
    publisher.join(timeout)
    if publisher.is_alive():
        cleanup_failures.append("publisher_thread_join_timeout")


def test_start_process_closes_both_pipes_when_process_construction_fails():
    class Pipe:
        def __init__(self, *, fail_close: bool = False) -> None:
            self.close_calls = 0
            self.fail_close = fail_close

        def close(self) -> None:
            self.close_calls += 1
            if self.fail_close:
                raise OSError("synthetic close failure")

    parent = Pipe(fail_close=True)
    child = Pipe()
    construction_error = RuntimeError("synthetic process construction failure")

    class Context:
        @staticmethod
        def Pipe(*, duplex: bool):
            assert duplex is True
            return parent, child

        @staticmethod
        def Process(**kwargs):
            raise construction_error

    try:
        _start_process(Context, target=object(), args=(), label="synthetic")
    except RuntimeError as exc:
        assert exc is construction_error
    else:
        raise AssertionError("Process construction failure was not propagated")
    assert parent.close_calls == 1
    assert child.close_calls == 1


def test_publisher_cleanup_records_a_bounded_join_timeout():
    class StuckPublisher:
        def __init__(self) -> None:
            self.join_timeouts: list[float] = []

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float) -> None:
            self.join_timeouts.append(timeout)

    publisher = StuckPublisher()
    cleanup_failures: list[str] = []
    _join_publisher_bounded(publisher, cleanup_failures, timeout=2.0)
    assert publisher.join_timeouts == [2.0]
    assert cleanup_failures == ["publisher_thread_join_timeout"]


def _host_command(record: dict[str, Any], *command, timeout: float = 8.0):
    assert record["process"].is_alive(), f"{record['label']} exited before its command"
    record["pipe"].send(command)
    result = _receive(record["pipe"], timeout)
    assert result[0] != "error", (record["label"], result)
    return result


def _close_host_normally(record: dict[str, Any]) -> tuple[Any, ...]:
    assert record["process"].is_alive(), f"{record['label']} exited before normal close"
    record["pipe"].send(("close",))
    record["close_requested"] = True
    result = _receive(record["pipe"], timeout=15.0)
    assert result[0] == "closed", (record["label"], result)
    process = record["process"]
    process.join(15)
    assert not process.is_alive(), f"{record['label']} did not exit within its bound"
    assert process.exitcode == 0, f"{record['label']} exited with {process.exitcode}"
    record["pipe"].close()
    process.close()
    record["closed"] = True
    return result


def _bounded_reap_test_process(
    record: dict[str, Any],
    forced: list[str],
    failures: list[str],
    *,
    expected_record: dict[str, Any] | None = None,
    expected_process: Any = None,
    expected_pid: int | None = None,
) -> None:
    """Close and reap one test-owned process, failing closed on unknown identity/state."""

    process = record.get("process")
    if expected_record is not None:
        if record is not expected_record:
            failures.append(f"{record.get('label', 'child')}:record_identity_mismatch")
            return
        if process is not expected_process:
            failures.append(f"{record.get('label', 'child')}:process_identity_mismatch")
            return
        if type(expected_pid) is not int or record.get("child_pid") != expected_pid:
            failures.append(f"{record.get('label', 'child')}:pid_identity_mismatch")
            return
        try:
            current_pid = process.pid
        except Exception:
            current_pid = None
        if current_pid != expected_pid and not (record.get("closed") and current_pid is None):
            failures.append(f"{record.get('label', 'child')}:process_pid_mismatch")
            return
    if record.get("closed"):
        return
    if process is None:
        failures.append(f"{record.get('label', 'child')}:process_missing")
        return
    pipe = record.get("pipe")
    if pipe is None:
        failures.append(f"{record.get('label', 'child')}:pipe_missing")
        return

    def alive() -> bool | None:
        try:
            return process.is_alive()
        except Exception as exc:
            failures.append(f"{record['label']}:state:{type(exc).__name__}")
            return None

    state = alive()
    if state is None:
        return
    if not state and not record["close_requested"]:
        failures.append(f"{record['label']}:exited_before_normal_close")
    if state and not record["close_requested"]:
        try:
            pipe.send(("close",))
            record["close_requested"] = True
        except Exception as exc:
            failures.append(f"{record['label']}:normal_close:{type(exc).__name__}")
    if record["close_requested"] and not record.get("close_acknowledged", False):
        try:
            reply_ready = pipe.poll(2.0)
        except Exception as exc:
            failures.append(f"{record['label']}:normal_close_poll:{type(exc).__name__}")
            reply_ready = False
        if reply_ready:
            try:
                reply = pipe.recv()
            except Exception as exc:
                failures.append(f"{record['label']}:normal_close_reply:{type(exc).__name__}")
            else:
                if not isinstance(reply, tuple) or not reply or reply[0] != "closed":
                    failures.append(f"{record['label']}:normal_close_reply:unexpected")
                else:
                    record["close_acknowledged"] = True
        else:
            failures.append(f"{record['label']}:normal_close_reply_timeout")
    try:
        process.join(5)
    except Exception as exc:
        failures.append(f"{record['label']}:normal_join:{type(exc).__name__}")
    state = alive()
    if state is None:
        return
    if state:
        forced.append(record["label"])
        try:
            process.terminate()
        except Exception as exc:
            failures.append(f"{record['label']}:terminate:{type(exc).__name__}")
        try:
            process.join(5)
        except Exception as exc:
            failures.append(f"{record['label']}:terminate_join:{type(exc).__name__}")
        state = alive()
        if state is None:
            return
    if state:
        try:
            process.kill()
        except Exception as exc:
            failures.append(f"{record['label']}:kill:{type(exc).__name__}")
        try:
            process.join(5)
        except Exception as exc:
            failures.append(f"{record['label']}:kill_join:{type(exc).__name__}")
        state = alive()
        if state is None:
            return
    if state:
        failures.append(f"{record['label']}:still_alive_after_kill")
        try:
            pipe.close()
        except Exception as exc:
            failures.append(f"{record['label']}:pipe_close:{type(exc).__name__}")
        return

    try:
        exitcode = process.exitcode
    except Exception as exc:
        failures.append(f"{record['label']}:exit_status:{type(exc).__name__}")
        exitcode = None
    record["observed_exitcode"] = exitcode
    if exitcode is None:
        failures.append(f"{record['label']}:exit_status_unknown")
    elif exitcode != 0:
        failures.append(f"{record['label']}:unexpected_exit:{exitcode}")
    try:
        pipe.close()
    except Exception as exc:
        failures.append(f"{record['label']}:pipe_close:{type(exc).__name__}")
    try:
        process.close()
    except Exception as exc:
        failures.append(f"{record['label']}:process_close:{type(exc).__name__}")
    else:
        record["closed"] = True


class _ReadProxyStrategy(bt.Strategy):
    params = (("market_control", None),)

    def __init__(self) -> None:
        self.samples: list[tuple[Any, ...]] = []
        self.published_sequences: tuple[int, int] | None = None

    def next(self) -> None:
        broker = self.broker
        open_orders = broker.get_open_orders()
        self.samples.append(
            (
                float(self.data.close[0]),
                float(self.data.volume[0]),
                float(broker.getcash()),
                float(broker.getvalue()),
                float(broker.getposition(self.data).size),
                tuple(order["order_id"] for order in open_orders),
            )
        )
        if len(self.samples) == 2:
            pipe = self.p.market_control
            sequences = []
            for index in (0, 1):
                pipe.send(("publish", index))
                response = _receive(pipe, timeout=8.0)
                if response[0] != "published" or response[1] != index:
                    raise AssertionError(f"synthetic publisher failed: {response!r}")
                sequences.append(response[2])
            self.published_sequences = (sequences[0], sequences[1])
        elif len(self.samples) == 3:
            self.env.runstop()
        elif len(self.samples) > 3:
            raise AssertionError("overlap event produced a duplicate Backtrader bar")


class _CapturingWriter(bt.WriterFile):
    """Capture the final writer dictionary while retaining real serialization."""

    def __init__(self, **kwargs):
        self.final_info = None
        super().__init__(**kwargs)

    def writedict(self, dct, level=0, recurse=False):
        if not recurse:
            self.final_info = dct
        return super().writedict(dct, level=level, recurse=recurse)


def test_cerebro_store_reads_account_and_history_then_streams_deduplicated_bars(tmp_path):
    """Two spawned CURVE hosts feed a read-only Store/Broker/Feed/Cerebro run."""

    context = multiprocessing.get_context("spawn")
    account_rpc, market_rpc, market_pub = _free_endpoints(3)
    guard_directory = tmp_path / "account-session-guard"
    guard_directory.mkdir(parents=True, exist_ok=True)
    account_server_keys = zmq.curve_keypair()
    market_server_keys = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    raw_account_service = _service_config(
        service_id=_ACCOUNT_SERVICE_ID,
        scope_ref=_ACCOUNT_SCOPE_REF,
        transport_ref=_ACCOUNT_TRANSPORT_REF,
        instance_id=_ACCOUNT_INSTANCE_ID,
        bind_ports=["service.account_read", "service.provider_session"],
        options={
            "role": "account_session_worker",
            "account_session_ref": "synthetic-account-session-v1",
        },
        rpc_bind=account_rpc,
        security_ref=_ACCOUNT_SECURITY_REF,
    )
    raw_market_service = _service_config(
        service_id=_MARKET_SERVICE_ID,
        scope_ref=_MARKET_SCOPE_REF,
        transport_ref=_MARKET_TRANSPORT_REF,
        instance_id=_MARKET_INSTANCE_ID,
        bind_ports=["service.market_source"],
        options={"role": "market_hub"},
        rpc_bind=market_rpc,
        security_ref=_MARKET_SECURITY_REF,
        market_bind=market_pub,
    )
    account_service = _start_process(
        context,
        _account_service_process,
        (
            raw_account_service,
            str(tmp_path / "account-registry.sqlite3"),
            str(tmp_path / "account-journal.sqlite3"),
            str(guard_directory),
            account_server_keys,
            client_public,
        ),
        "synthetic-account-service-host",
    )
    market_service = None
    runtime: ServiceClientRuntime | None = None
    proxy: ServiceReadProxy | None = None
    broker: BtApiBroker | None = None
    forced_cleanup: list[str] = []
    cleanup_failures: list[str] = []
    timer: threading.Timer | None = None
    try:
        account_ready = _receive(account_service["pipe"])
        assert account_ready[0] == "ready", account_ready
        assert account_ready[1] == account_rpc
        assert account_ready[2]["host"] == "started"
        assert account_ready[2]["ready"] is True
        assert account_ready[2]["connect_calls"] == 1
        assert account_ready[2]["read_calls"] == 1
        assert account_ready[2]["close_calls"] == 0
        assert account_ready[2]["provider_write_methods"] == ()

        market_service = _start_process(
            context,
            _market_service_process,
            (
                raw_market_service,
                str(tmp_path / "market-registry.sqlite3"),
                market_server_keys,
                client_public,
            ),
            "synthetic-market-service-host",
        )
        market_ready = _receive(market_service["pipe"])
        assert market_ready[0] == "ready", market_ready
        assert market_ready[1:3] == (market_rpc, market_pub)
        assert market_ready[3]["host"] == "started"
        assert market_ready[3]["readiness"]["ready"] is True
        assert market_ready[3]["source_starts"] == 0
        assert market_ready[3]["source_stops"] == 0

        raw_client = _client_config(account_rpc, market_rpc, market_pub)
        config = parse_client_config(raw_client)
        identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            _CLIENT_PRINCIPAL,
            _STRATEGY_REF,
        )
        scope_by_ref = {
            _ACCOUNT_SCOPE_REF: WireScope(
                _DOMAIN_REF,
                account_ref=_ACCOUNT_REF,
                strategy_ref=_STRATEGY_REF,
            ),
            _MARKET_SCOPE_REF: WireScope(_DOMAIN_REF, strategy_ref=_STRATEGY_REF),
        }
        peer_by_service = {
            _ACCOUNT_SERVICE_ID: WireIdentity(
                WireRole.SERVICE,
                "principal-account-service",
                _ACCOUNT_SERVICE_ID,
            ),
            _MARKET_SERVICE_ID: WireIdentity(
                WireRole.SERVICE,
                "principal-market-service",
                _MARKET_SERVICE_ID,
            ),
        }
        account_client_keys = ClientCurveKeys(
            account_server_keys[0],
            client_public,
            client_secret,
        )
        market_client_keys = ClientCurveKeys(
            market_server_keys[0],
            client_public,
            client_secret,
        )
        runtime = ServiceClientRuntime(
            config,
            identity=identity,
            scope_resolver=lambda scope_ref: scope_by_ref[scope_ref],
            peer_resolver=lambda service_id: peer_by_service[service_id],
            transport_factory=ZmqTransportFactory(
                {
                    _ACCOUNT_SECURITY_REF: account_client_keys,
                    _MARKET_SECURITY_REF: market_client_keys,
                }
            ),
            requested_operations={
                "store.account": _ACCOUNT_OPERATIONS,
                "store.market": _MARKET_OPERATIONS,
            },
        )
        runtime.start()
        assert runtime.healthy is True
        assert len(runtime.bindings) == 2
        assert {binding.mount: binding.operations for binding in runtime.bindings} == {
            "store.account": _ACCOUNT_OPERATIONS,
            "store.market": _MARKET_OPERATIONS,
        }

        account_client = ServiceAccountClient(
            runtime,
            "store.account",
            account_ref=_ACCOUNT_REF,
            expected_account=_ACCOUNT_KEY,
            required_coverage=(_RESOURCE,),
            require_open_orders=True,
        )
        market_client = ServiceMarketClient(
            runtime,
            "store.market",
            _MARKET_KEY,
            subscriber_factory=ZmqMarketTransportFactory(
                {_MARKET_SECURITY_REF: market_client_keys}
            ),
            stream_scope=WireScope(_DOMAIN_REF),
            head_check_interval_seconds=0.25,
        )
        proxy = ServiceReadProxy(
            account_client,
            {
                _SYMBOL: ServiceFeedBinding(
                    market_client,
                    _RESOURCE,
                    "unit",
                    "1m",
                    history_start_utc=_HISTORY_START,
                    history_end_utc=_HISTORY_END,
                )
            },
            valuation_currency="USD",
            position_mode="net",
            default_history_limit=3,
            clock=lambda: _PROXY_CLOCK,
        )
        assert not callable(getattr(proxy, "submit_order", None))
        assert not callable(getattr(proxy, "cancel_order", None))

        store = BtApiStore(api=proxy)
        broker = store.getbroker(
            market_data_only=True,
            position_mode="net",
            force_refresh_queries=True,
        )
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        writer_output = io.StringIO()
        cerebro.addwriter(
            _CapturingWriter,
            out=writer_output,
            csv=False,
            close_out=False,
        )
        data = store.getdata(
            dataname=_SYMBOL,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            backfill_start=True,
            dispatch_ticks=False,
            dispatch_orderbooks=False,
        )
        cerebro.adddata(data, name=_SYMBOL)

        # The first worker baseline contains a real v2 open-order fact.  A
        # control-side full refresh replaces it with a complete empty set.
        broker.start()
        initial_orders = broker.get_open_orders()
        assert len(initial_orders) == 1
        assert initial_orders[0]["order_id"] == "synthetic-open-order-1"
        assert initial_orders[0]["quantity"] == 1.0
        assert broker.getcash() == 80.0
        assert broker.getvalue() == 105.0
        assert broker.getposition(data).size == 2.5
        refreshed = _host_command(account_service, "refresh")
        assert refreshed[0] == "refreshed", refreshed
        refreshed_view = account_client.refresh()
        assert refreshed_view.observation.open_orders == ()
        assert refreshed_view.observation.open_orders_complete is True
        assert broker.get_open_orders() == []
        account_status = _host_command(account_service, "status")
        assert account_status[1]["connect_calls"] == 1
        assert account_status[1]["read_calls"] == 2
        assert account_status[1]["close_calls"] == 0

        cerebro.addstrategy(_ReadProxyStrategy, market_control=market_service["pipe"])
        timer = threading.Timer(25.0, cerebro.runstop)
        timer.daemon = True
        timer.start()
        strategies = cerebro.run(runonce=False, preload=False)
        timer.cancel()
        timer.join(2.0)
        strategy = strategies[0]
        writer = cerebro.runwriters[0]
        assert (
            writer.final_info["Cerebro"]["Strategies"]["_ReadProxyStrategy"]["Analyzers"]["Value"][
                "End"
            ]
            == 105.0
        )
        assert "End: 105.0" in writer_output.getvalue()
        assert strategy.samples == [
            (100.5, 3.0, 80.0, 105.0, 2.5, ()),
            (101.5, 4.0, 80.0, 105.0, 2.5, ()),
            (102.5, 5.0, 80.0, 105.0, 2.5, ()),
        ]
        assert strategy.published_sequences == (1, 2)
        assert broker.get_market_data_only_audit()["total_rejected"] == 0
        assert proxy.is_connected is False
        assert account_client.healthy is False
        assert market_client.healthy is False
        assert runtime.state == "registered"
        runtime.close()
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        assert runtime.unregister_uncertainties == 0

        market_status = _host_command(market_service, "status")
        assert market_status[1]["history_calls"] == 1
        assert market_status[1]["source_starts"] == 1
        assert market_status[1]["source_stops"] == 1
        assert market_status[1]["readiness"]["active_upstreams"] == 0
        assert market_status[1]["readiness"]["active_registrations"] == 0
        account_status = _host_command(account_service, "status")
        assert account_status[1]["connect_calls"] == 1
        assert account_status[1]["read_calls"] == 2
        assert account_status[1]["close_calls"] == 0

        market_closed = _close_host_normally(market_service)
        assert market_closed[1]["host"] == "closed"
        assert market_closed[1]["source_starts"] == 1
        assert market_closed[1]["source_stops"] == 1
        account_closed = _close_host_normally(account_service)
        assert account_closed[1]["host"] == "closed"
        assert account_closed[1]["ready"] is False
        assert account_closed[1]["connect_calls"] == 1
        assert account_closed[1]["read_calls"] == 2
        assert account_closed[1]["close_calls"] == 1
    finally:
        if timer is not None:
            timer.cancel()
            timer.join(2.0)
        if broker is not None:
            try:
                broker.stop()
            except Exception as exc:
                cleanup_failures.append(f"broker_stop:{type(exc).__name__}")
        if proxy is not None:
            try:
                proxy.close()
            except Exception as exc:
                cleanup_failures.append(f"proxy_close:{type(exc).__name__}")
        if runtime is not None and runtime.state != "closed":
            try:
                runtime.close()
            except Exception as exc:
                cleanup_failures.append(f"runtime_close:{type(exc).__name__}")
        for record in (market_service, account_service):
            if record is not None:
                _bounded_reap_test_process(record, forced_cleanup, cleanup_failures)
        if forced_cleanup or cleanup_failures:
            raise AssertionError(
                "integration cleanup was not normal: "
                f"forced={tuple(forced_cleanup)}, failures={tuple(cleanup_failures)}"
            )


def test_cerebro_store_feed_consumes_service_orderbook_with_bound_source(tmp_path):
    """A real local ServiceHost delivers one typed L2 image through the Feed."""

    context = multiprocessing.get_context("spawn")
    market_rpc, market_pub = _free_endpoints(2)
    market_server_keys = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    raw_market_service = _service_config(
        service_id=_MARKET_SERVICE_ID,
        scope_ref=_MARKET_SCOPE_REF,
        transport_ref=_MARKET_TRANSPORT_REF,
        instance_id=_MARKET_INSTANCE_ID,
        bind_ports=["service.market_source"],
        options={"role": "market_hub"},
        rpc_bind=market_rpc,
        security_ref=_MARKET_SECURITY_REF,
        market_bind=market_pub,
    )
    market_service = _start_process(
        context,
        _market_service_process,
        (
            raw_market_service,
            str(tmp_path / "orderbook-market-registry.sqlite3"),
            market_server_keys,
            client_public,
            _ORDERBOOK_KEY,
        ),
        "synthetic-orderbook-service-host",
    )
    runtime: ServiceClientRuntime | None = None
    proxy: ServiceReadProxy | None = None
    broker: BtApiBroker | None = None
    publisher: threading.Thread | None = None
    watchdog: threading.Timer | None = None
    forced_cleanup: list[str] = []
    cleanup_failures: list[str] = []
    try:
        market_ready = _receive(market_service["pipe"])
        assert market_ready[0] == "ready", market_ready
        assert market_ready[1:3] == (market_rpc, market_pub)
        assert market_ready[3]["host"] == "started"
        assert market_ready[3]["readiness"]["ready"] is True
        assert market_ready[3]["source_starts"] == 0

        raw_client = _client_config("tcp://127.0.0.1:1", market_rpc, market_pub)
        client_settings = raw_client["clients"]["gateway"]["settings"]
        client_settings["bindings"] = [
            binding
            for binding in client_settings["bindings"]
            if binding["mount"] == "store.market"
        ]
        raw_client["communication"]["profiles"].pop(_ACCOUNT_CLIENT_TRANSPORT_REF)
        config = parse_client_config(raw_client)
        identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            _CLIENT_PRINCIPAL,
            _STRATEGY_REF,
        )
        market_client_keys = ClientCurveKeys(
            market_server_keys[0],
            client_public,
            client_secret,
        )
        runtime = ServiceClientRuntime(
            config,
            identity=identity,
            scope_resolver=lambda scope_ref: {
                _MARKET_SCOPE_REF: WireScope(_DOMAIN_REF, strategy_ref=_STRATEGY_REF)
            }[scope_ref],
            peer_resolver=lambda service_id: {
                _MARKET_SERVICE_ID: WireIdentity(
                    WireRole.SERVICE,
                    "principal-market-service",
                    _MARKET_SERVICE_ID,
                )
            }[service_id],
            transport_factory=ZmqTransportFactory(
                {_MARKET_SECURITY_REF: market_client_keys}
            ),
            requested_operations={"store.market": _MARKET_OPERATIONS},
        )
        runtime.start()
        assert runtime.healthy is True
        assert len(runtime.bindings) == 1
        assert runtime.bindings[0].mount == "store.market"

        market_client = ServiceMarketClient(
            runtime,
            "store.market",
            _ORDERBOOK_KEY,
            subscriber_factory=ZmqMarketTransportFactory(
                {_MARKET_SECURITY_REF: market_client_keys}
            ),
            stream_scope=WireScope(_DOMAIN_REF),
            head_check_interval_seconds=0.25,
            require_source_descriptor=True,
        )

        class _SyntheticReadOnlyAccountClient:
            expected_account = _ACCOUNT_KEY
            required_coverage = (_RESOURCE,)
            require_open_orders = True

            def __init__(self):
                self.closed = False
                self.read_calls = 0
                self.view = SimpleNamespace(observation=_account_observation(2))

            def refresh(self):
                self.read_calls += 1
                return self.view

            def snapshot(self):
                return self.view

            def close(self):
                self.closed = True

        account_client = _SyntheticReadOnlyAccountClient()
        binding = ServiceOrderBookBinding(
            market_client,
            _RESOURCE,
            "unit",
            quantity_multiplier="2",
            max_depth=2,
            max_event_age_seconds="5",
        )
        proxy = ServiceReadProxy(
            account_client,
            {_SYMBOL: binding},
            valuation_currency="USD",
            position_mode="net",
            clock=lambda: datetime.now(UTC),
        )
        assert not callable(getattr(proxy, "submit_order", None))
        store = BtApiStore(api=proxy)
        broker = store.getbroker(
            market_data_only=True,
            position_mode="net",
            force_refresh_queries=True,
        )
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        data = store.getdata(
            dataname=_SYMBOL,
            timeframe=bt.TimeFrame.Ticks,
            compression=1,
            backfill_start=False,
            dispatch_orderbooks=True,
            orderbook_as_ticks=True,
            qcheck=0.01,
        )
        cerebro.adddata(data, name=_SYMBOL)

        class _OneOrderBookStrategy(bt.Strategy):
            params = (("proxy", None),)

            def __init__(self):
                self.received = []

            def notify_orderbook(self, book):
                descriptor = self.p.proxy.orderbook_source_descriptor(_SYMBOL)
                self.received.append((book, descriptor, float(self.data.close[0])))
                self.env.runstop()

        cerebro.addstrategy(_OneOrderBookStrategy, proxy=proxy)
        publish_errors: list[str] = []
        publish_receipts: list[tuple[Any, ...]] = []

        def publish_after_subscribe():
            deadline = time.monotonic() + 10.0
            try:
                while time.monotonic() < deadline:
                    status = _host_command(market_service, "status", timeout=8.0)
                    if status[1]["source_starts"] == 1:
                        publish_receipts.append(
                            _host_command(market_service, "publish", 0, timeout=8.0)
                        )
                        return
                    time.sleep(0.02)
                publish_errors.append("market_subscription_timeout")
                cerebro.runstop()
            except BaseException as exc:
                publish_errors.append(type(exc).__name__)
                cerebro.runstop()

        publisher = threading.Thread(
            target=publish_after_subscribe,
            name="synthetic-orderbook-publisher",
            daemon=True,
        )
        watchdog = threading.Timer(15.0, cerebro.runstop)
        watchdog.daemon = True
        watchdog.start()
        publisher.start()
        strategies = cerebro.run(runonce=False, preload=False)
        watchdog.cancel()
        publisher.join(12.0)
        assert not publisher.is_alive(), "synthetic orderbook publisher exceeded its bound"
        assert publish_errors == []
        assert len(publish_receipts) == 1
        assert publish_receipts[0][0] == "published"
        assert strategies and len(strategies[0].received) == 1

        book, descriptor, midpoint = strategies[0].received[0]
        assert type(book).__name__ == "OrderBookSnapshot"
        assert descriptor.key == _ORDERBOOK_KEY
        assert descriptor.stream_id == _ORDERBOOK_KEY.stream_id
        assert descriptor.provider == _INSTRUMENT.provider
        assert descriptor.epoch
        assert descriptor.connection_generation == 1
        assert book.source == descriptor.source
        assert book.symbol == _SYMBOL
        assert book.exchange == _INSTRUMENT.venue
        assert book.sequence == 1
        assert book.previous_sequence is None
        assert book.snapshot_or_delta == "snapshot"
        assert book.continuity_status == "snapshot"
        assert book.stale is False
        assert book.bids == [(100.0, 6.0), (99.5, 4.0)]
        assert book.asks == [(100.5, 8.0), (101.0, 10.0)]
        assert midpoint == 100.25
        assert account_client.read_calls == 1
        assert proxy.is_connected is False
        assert account_client.closed is True
        assert market_client.healthy is False

        market_status = _host_command(market_service, "status")
        assert market_status[1]["source_starts"] == 1
        assert market_status[1]["source_stops"] == 1
        assert market_status[1]["readiness"]["active_upstreams"] == 0
        assert market_status[1]["readiness"]["active_registrations"] == 0
        runtime.close()
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        market_closed = _close_host_normally(market_service)
        assert market_closed[1]["host"] == "closed"
        assert market_closed[1]["source_starts"] == 1
        assert market_closed[1]["source_stops"] == 1
    finally:
        if watchdog is not None:
            watchdog.cancel()
            watchdog.join(2.0)
        _join_publisher_bounded(publisher, cleanup_failures, timeout=2.0)
        if broker is not None:
            try:
                broker.stop()
            except Exception as exc:
                cleanup_failures.append(f"broker_stop:{type(exc).__name__}")
        if proxy is not None:
            try:
                proxy.close()
            except Exception as exc:
                cleanup_failures.append(f"proxy_close:{type(exc).__name__}")
        if runtime is not None and runtime.state != "closed":
            try:
                runtime.close()
            except Exception as exc:
                cleanup_failures.append(f"runtime_close:{type(exc).__name__}")
        if market_service is not None:
            _bounded_reap_test_process(market_service, forced_cleanup, cleanup_failures)
        if forced_cleanup or cleanup_failures:
            raise AssertionError(
                "orderbook integration cleanup was not normal: "
                f"forced={tuple(forced_cleanup)}, failures={tuple(cleanup_failures)}"
            )


def test_i52_a2_v2_readonly_factory_discovers_and_registers_two_hosts_without_business_calls(
    tmp_path, record_property
):
    """Exercise only V2 account/market discovery, registration and normal close."""

    context = multiprocessing.get_context("spawn")
    account_rpc, market_rpc, market_pub = _free_endpoints(3)
    account_server_keys = zmq.curve_keypair()
    market_server_keys = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    raw_account_service = _service_config(
        service_id=_ACCOUNT_SERVICE_ID,
        scope_ref=_ACCOUNT_SCOPE_REF,
        transport_ref=_ACCOUNT_TRANSPORT_REF,
        instance_id=_ACCOUNT_INSTANCE_ID,
        bind_ports=["service.account_read"],
        options={
            "role": "account_session_worker",
            "account_session_ref": "synthetic-a2-control-only",
        },
        rpc_bind=account_rpc,
        security_ref=_ACCOUNT_SECURITY_REF,
    )
    raw_market_service = _service_config(
        service_id=_MARKET_SERVICE_ID,
        scope_ref=_MARKET_SCOPE_REF,
        transport_ref=_MARKET_TRANSPORT_REF,
        instance_id=_MARKET_INSTANCE_ID,
        bind_ports=["service.market_source"],
        options={"role": "market_hub"},
        rpc_bind=market_rpc,
        security_ref=_MARKET_SECURITY_REF,
        market_bind=market_pub,
    )
    account_service = None
    market_service = None
    factory = None
    owner = None
    cleanup_failures: list[str] = []
    forced_cleanup: list[str] = []
    owned_children: dict[int, tuple[dict[str, Any], Any, int | None]] = {}

    def register_owned_child(record: dict[str, Any], child_pid: int | None) -> None:
        process = record["process"]
        record["child_pid"] = child_pid
        owned_children[id(record)] = (record, process, child_pid)

    def remember_owned_child(record: dict[str, Any]) -> int | None:
        process = record["process"]
        try:
            child_pid = process.pid
        except Exception as exc:
            child_pid = None
            cleanup_failures.append(f"{record['label']}:pid_capture:{type(exc).__name__}")
        register_owned_child(record, child_pid)
        return child_pid

    reap_attempted: set[int] = set()

    def reap_owned_child(record: dict[str, Any] | None) -> None:
        if record is None:
            return
        marker = id(record)
        if marker in reap_attempted:
            return
        reap_attempted.add(marker)
        expected = owned_children.get(marker)
        if expected is None:
            cleanup_failures.append(f"{record.get('label', 'child')}:ownership_unverified")
            return
        expected_record, expected_process, expected_pid = expected
        if expected_record is not record or record.get("process") is not expected_process:
            cleanup_failures.append(f"{record['label']}:ownership_identity_mismatch")
            return
        try:
            _bounded_reap_test_process(
                record,
                forced_cleanup,
                cleanup_failures,
                expected_record=expected_record,
                expected_process=expected_process,
                expected_pid=expected_pid,
            )
        except BaseException as exc:
            cleanup_failures.append(f"{record['label']}:reaper:{type(exc).__name__}")

    def close_owned_handle(handle, label: str) -> None:
        try:
            handle.close()
        except BaseException as exc:
            cleanup_failures.append(f"{label}:{type(exc).__name__}")

    def start_owned_host(target, args: tuple[Any, ...], label: str) -> dict[str, Any]:
        parent_pipe, child_pipe = context.Pipe(duplex=True)
        try:
            process = context.Process(
                target=target,
                args=(child_pipe, *args),
                name=label,
            )
        except BaseException:
            close_owned_handle(parent_pipe, f"{label}:parent_pipe_close")
            close_owned_handle(child_pipe, f"{label}:child_pipe_close")
            raise

        record: dict[str, Any] = {
            "label": label,
            "process": process,
            "pipe": parent_pipe,
            "closed": False,
            "close_requested": False,
            "close_acknowledged": False,
        }
        try:
            process.start()
        except BaseException:
            try:
                child_pid = process.pid
            except Exception as exc:
                child_pid = None
                cleanup_failures.append(f"{label}:pid_capture_after_start_error:{type(exc).__name__}")
            if type(child_pid) is int:
                register_owned_child(record, child_pid)
                close_owned_handle(child_pipe, f"{label}:child_pipe_close_after_start_error")
                reap_owned_child(record)
                close_owned_handle(child_pipe, f"{label}:child_pipe_close_after_reap")
            else:
                close_owned_handle(parent_pipe, f"{label}:parent_pipe_close_after_start_error")
                close_owned_handle(child_pipe, f"{label}:child_pipe_close_after_start_error")
                try:
                    process.close()
                except BaseException as exc:
                    cleanup_failures.append(f"{label}:process_close_after_start_error:{type(exc).__name__}")
            raise

        child_pid = remember_owned_child(record)
        if type(child_pid) is not int:
            close_owned_handle(child_pipe, f"{label}:child_pipe_close_without_pid")
            close_owned_handle(parent_pipe, f"{label}:parent_pipe_close_without_pid")
            reap_owned_child(record)
            raise RuntimeError(f"{label}:started child PID could not be verified")
        try:
            child_pipe.close()
        except BaseException:
            # Keep the original close error; the child identity was recorded first.
            close_owned_handle(child_pipe, f"{label}:child_pipe_close_retry")
            reap_owned_child(record)
            close_owned_handle(child_pipe, f"{label}:child_pipe_close_after_reap")
            raise
        return record

    try:
        account_service = start_owned_host(
            _account_read_control_host_process,
            (
                raw_account_service,
                str(tmp_path / "a2-account-registry.sqlite3"),
                str(tmp_path / "a2-account-journal.sqlite3"),
                account_server_keys,
                client_public,
            ),
            "i52-a2-synthetic-account-read-host",
        )
        account_ready = _receive(account_service["pipe"])
        assert account_ready[0] == "ready", account_ready
        assert account_ready[1] == account_rpc
        assert account_ready[2]["host"] == "started"
        assert account_ready[2]["capabilities"] == (
            ("service.account_read", tuple(sorted(_ACCOUNT_HOST_OPERATIONS))),
        )
        assert account_ready[2]["internal_ports"] == ()
        assert account_ready[2]["account_snapshot_calls"] == 0
        assert account_ready[2]["order_write_calls"] == 0

        market_service = start_owned_host(
            _market_service_process,
            (
                raw_market_service,
                str(tmp_path / "a2-market-registry.sqlite3"),
                market_server_keys,
                client_public,
                _MARKET_KEY,
                True,
            ),
            "i52-a2-synthetic-market-host",
        )
        market_ready = _receive(market_service["pipe"])
        assert market_ready[0] == "ready", market_ready
        assert market_ready[1:3] == (market_rpc, market_pub)
        assert market_ready[3]["host"] == "started"
        assert market_ready[3]["readiness"]["ready"] is True
        assert market_ready[3]["capabilities"] == (
            ("service.market_source", tuple(sorted(_MARKET_HOST_OPERATIONS))),
        )
        assert market_ready[3]["internal_ports"] == ()
        assert market_ready[3]["publisher_endpoint"] == market_pub
        assert market_ready[3]["host_active_registrations"] == 0
        assert market_ready[3]["readiness"]["active_registrations"] == 0
        assert market_ready[3]["provider_poll_calls"] == 0
        assert market_ready[3]["source_starts"] == 0
        assert market_ready[3]["history_calls"] == 0
        assert all(value == 0 for value in market_ready[3]["source_diagnostics"].values())

        raw_client_config = _client_config(account_rpc, market_rpc, market_pub)
        raw_client_config["clients"]["gateway"]["settings"]["options"][
            "heartbeat_interval_seconds"
        ] = _A2_HEARTBEAT_SECONDS
        config = parse_client_config(raw_client_config)
        client_identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            _CLIENT_PRINCIPAL,
            _STRATEGY_REF,
        )
        account_peer = WireIdentity(
            WireRole.SERVICE,
            "principal-account-service",
            _ACCOUNT_SERVICE_ID,
        )
        market_peer = WireIdentity(
            WireRole.SERVICE,
            "principal-market-service",
            _MARKET_SERVICE_ID,
        )
        account_client_keys = ClientCurveKeys(
            account_server_keys[0], client_public, client_secret
        )
        market_client_keys = ClientCurveKeys(market_server_keys[0], client_public, client_secret)
        transport_factory = ZmqTransportFactory(
            {
                _ACCOUNT_SECURITY_REF: account_client_keys,
                _MARKET_SECURITY_REF: market_client_keys,
            }
        )
        subscriber_factory_calls: list[tuple[Any, Any]] = []

        def subscriber_factory(binding, scope):
            subscriber_factory_calls.append((binding, scope))
            raise AssertionError("subscriber must not be constructed before market.subscribe")

        route_references = ReferencesV2(
            strategy="strategy/shared_configured_observer",
            provider="provider/service_boundary",
            endpoint="endpoint/paper",
            account="account/paper",
            credential="credential/paper",
            scope="scope/paper",
            product="product/synthetic_spot",
            data_source="data_source/market_feed",
            clock="clock/exchange_utc",
        )
        route = TrustedRouteV2(
            Environment.PAPER,
            route_references,
            ("account.read", "market.read"),
            (("enabled", "bool", True),),
        )
        sdk_references = SdkRouteReferencesV2(
            strategy=SdkRouteReference(route_references.strategy, _STRATEGY_REF),
            provider=SdkRouteReference(route_references.provider, _ACCOUNT_KEY.provider),
            endpoint=SdkRouteReference(route_references.endpoint, "a2-readonly-bundle-v1"),
            account=SdkRouteReference(route_references.account, _ACCOUNT_REF),
            credential=SdkRouteReference(
                route_references.credential, "a2-synthetic-curves-v1"
            ),
            scope=SdkRouteReference(route_references.scope, _ACCOUNT_SCOPE_REF),
            product=SdkRouteReference(route_references.product, _INSTRUMENT.product_type),
            data_source=SdkRouteReference(route_references.data_source, _MARKET_KEY.source_ref),
            clock=SdkRouteReference(route_references.clock, "a2-synthetic-clock-v1"),
        )
        account_scope = WireScope(
            _DOMAIN_REF,
            account_ref=_ACCOUNT_REF,
            strategy_ref=_STRATEGY_REF,
        )
        market_scope = WireScope(_DOMAIN_REF, strategy_ref=_STRATEGY_REF)
        stream_scope = WireScope(_DOMAIN_REF)
        scope_dimensions = {
            "account_ref",
            "account_refs",
            "strategy_ref",
            "run_id",
            "manual_book_ref",
            "portfolio_ref",
            "group_id",
            "leg_id",
        }
        scope_context_field = next(
            item.name for item in fields(WireScope) if item.name not in scope_dimensions
        )
        endpoint_bundle = "a2-readonly-bundle-v1"
        credential_bundle = "a2-synthetic-curves-v1"
        account_target = SdkReadOnlyTargetV2(
            service_id=_ACCOUNT_SERVICE_ID,
            instance_id=_ACCOUNT_INSTANCE_ID,
            transport_ref=_ACCOUNT_CLIENT_TRANSPORT_REF,
            security_profile_ref=_ACCOUNT_SECURITY_REF,
            peer=account_peer,
            rpc_endpoint=account_rpc,
            market_endpoint=None,
        )
        market_target = SdkReadOnlyTargetV2(
            service_id=_MARKET_SERVICE_ID,
            instance_id=_MARKET_INSTANCE_ID,
            transport_ref=_MARKET_CLIENT_TRANSPORT_REF,
            security_profile_ref=_MARKET_SECURITY_REF,
            peer=market_peer,
            rpc_endpoint=market_rpc,
            market_endpoint=market_pub,
        )
        spec = SdkReadOnlySpecV2(
            route=route,
            references=sdk_references,
            environment=SdkEnvironmentMapping(Environment.PAPER, "paper"),
            client_config=config,
            identity=client_identity,
            peer=account_peer,
            client_principal_ref=_CLIENT_PRINCIPAL,
            service_principal_ref=account_peer.principal_ref,
            account_key=AccountKey(
                _ACCOUNT_KEY.provider,
                _ACCOUNT_KEY.venue,
                _ACCOUNT_KEY.environment,
                _ACCOUNT_REF,
            ),
            account_resource=_RESOURCE,
            instrument=_INSTRUMENT,
            subscription_key=_MARKET_KEY,
            account_scope=account_scope,
            market_scope=market_scope,
            stream_scope=stream_scope,
            account_ref=_ACCOUNT_REF,
            service_id=_ACCOUNT_SERVICE_ID,
            instance_id=_ACCOUNT_INSTANCE_ID,
            account_scope_ref=_ACCOUNT_SCOPE_REF,
            market_scope_ref=_MARKET_SCOPE_REF,
            transport_ref=_ACCOUNT_CLIENT_TRANSPORT_REF,
            security_profile_ref=_ACCOUNT_SECURITY_REF,
            rpc_endpoint=account_rpc,
            market_endpoint=market_pub,
            venue=_INSTRUMENT.venue,
            product_type=_INSTRUMENT.product_type,
            data_source_ref=_MARKET_KEY.source_ref,
            entitlement_ref=_MARKET_KEY.entitlement_ref,
            market_source_expectation=SdkMarketSourceExpectation(
                source="synthetic.servicehost.market",
                clock_domain_id="synthetic-provider-clock",
                clock_source_session_id="synthetic-session-1",
                clock_source="synthetic-provider-clock",
            ),
            scope_context_field=scope_context_field,
            scope_context_ref=_DOMAIN_REF,
            clock_binding=SdkClockBinding(
                "a2-synthetic-clock-v1",
                lambda: _PROXY_CLOCK,
            ),
            data_name=_SYMBOL,
            history_start_utc=_HISTORY_START,
            history_end_utc=_HISTORY_END,
            valuation_currency="USD",
            position_mode="net",
            qty_unit="unit",
            transport_factory=transport_factory,
            subscriber_factory=subscriber_factory,
            targets=SdkReadOnlyTargetsV2(
                endpoint_ref=endpoint_bundle,
                credential_ref=credential_bundle,
                account=account_target,
                market=market_target,
            ),
        )
        run_id = "i52-a2-control-run-001"
        factory = SdkReadOnlyFacadeFactory(spec)
        assert factory.preflight(route, run_id=run_id) is True
        owner = factory.owner
        assert factory.build(run_id=run_id) is owner
        assert owner is factory.owner
        assert owner.state == "ready"
        runtime = owner.runtime
        assert isinstance(runtime, ServiceClientRuntime)
        assert runtime.run_id == run_id
        assert runtime.state == "registered"
        assert runtime.healthy is True
        bindings = {binding.mount: binding for binding in runtime.bindings}
        assert set(bindings) == {"store.account", "store.market"}
        assert {
            mount: binding.operations for mount, binding in bindings.items()
        } == {
            "store.account": _ACCOUNT_OPERATIONS,
            "store.market": _MARKET_OPERATIONS,
        }
        assert all(binding.scope.run_id == run_id for binding in bindings.values())
        assert bindings["store.account"].service_id == _ACCOUNT_SERVICE_ID
        assert bindings["store.market"].service_id == _MARKET_SERVICE_ID
        account_view = runtime.account_binding_view(
            "store.account",
            _ACCOUNT_REF,
            required_operations=_ACCOUNT_OPERATIONS,
        )
        market_view = runtime.market_binding_view(
            "store.market",
            required_operations=_MARKET_OPERATIONS,
        )
        assert (
            account_view.service_id,
            account_view.account_ref,
            account_view.operations,
        ) == (_ACCOUNT_SERVICE_ID, _ACCOUNT_REF, _ACCOUNT_OPERATIONS)
        assert (
            market_view.service_id,
            market_view.peer,
            market_view.market_endpoint,
        ) == (_MARKET_SERVICE_ID, market_peer, market_pub)
        assert subscriber_factory_calls == []

        allowed_control = {"service.discover", "service.register"}
        account_before_close = _host_command(account_service, "status")[1]
        market_before_close = _host_command(market_service, "status")[1]
        for status in (account_before_close, market_before_close):
            assert set(status["request_operations"]) <= allowed_control
            assert status["request_operations"].count("service.discover") == 1
            assert status["request_operations"].count("service.register") == 1
        assert len(account_before_close["request_operations"]) == 2
        assert len(market_before_close["request_operations"]) == 2
        assert market_before_close["host_active_registrations"] == 1
        assert market_before_close["publisher_endpoint"] == market_pub
        assert account_before_close["account_snapshot_calls"] == 0
        assert account_before_close["order_write_calls"] == 0
        assert market_before_close["market_subscribe_calls"] == 0
        assert market_before_close["market_unsubscribe_calls"] == 0
        assert market_before_close["source_starts"] == 0
        assert market_before_close["source_stops"] == 0
        assert market_before_close["history_calls"] == 0
        assert market_before_close["provider_poll_calls"] == 0
        assert all(value == 0 for value in market_before_close["source_diagnostics"].values())

        owner.close()
        assert owner.state == "closed"
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        assert runtime.unregister_uncertainties == 0
        assert runtime.unknown_registration_count == 0
        assert subscriber_factory_calls == []
        account_unregistered = _host_command(account_service, "status")[1]
        market_unregistered = _host_command(market_service, "status")[1]
        for status in (account_unregistered, market_unregistered):
            assert status["request_operations"].count("service.discover") == 1
            assert status["request_operations"].count("service.register") == 1
            assert status["request_operations"].count("service.unregister") == 1
        assert market_unregistered["host_active_registrations"] == 0
        assert market_unregistered["readiness"]["active_registrations"] == 0
        assert market_unregistered["publisher_endpoint"] == market_pub
        assert market_unregistered["provider_poll_calls"] == 0

        account_closed = _close_host_normally(account_service)
        account_service["observed_exitcode"] = 0
        market_closed = _close_host_normally(market_service)
        market_service["observed_exitcode"] = 0
        assert account_closed[1]["host"] == "closed"
        assert market_closed[1]["host"] == "closed"
        assert market_closed[1]["publisher_endpoint"] is None
        assert market_closed[1]["host_active_registrations"] == 0
        assert market_closed[1]["readiness"]["active_registrations"] == 0
        assert market_closed[1]["provider_poll_calls"] == 0
        for status in (account_closed[1], market_closed[1]):
            operations = status["request_operations"]
            assert set(operations) <= {"service.discover", "service.register", "service.unregister"}
            assert operations.count("service.discover") == 1
            assert operations.count("service.register") == 1
            assert operations.count("service.unregister") == 1
            assert status["cleanup_failures"] == ()
        assert account_closed[1]["account_snapshot_calls"] == 0
        assert account_closed[1]["order_write_calls"] == 0
        assert market_closed[1]["market_subscribe_calls"] == 0
        assert market_closed[1]["market_unsubscribe_calls"] == 0
        assert market_closed[1]["source_starts"] == 0
        assert market_closed[1]["source_stops"] == 0
        assert market_closed[1]["history_calls"] == 0
        assert market_closed[1]["provider_poll_calls"] == 0
        assert all(value == 0 for value in market_closed[1]["source_diagnostics"].values())
        assert subscriber_factory_calls == []

        record_property("i52_a2_evidence_level", "local synthetic control-plane only")
        record_property(
            "i52_a2_installed_ports",
            "account=service.account_read; market=service.market_source",
        )
        record_property(
            "i52_a2_not_installed_ports",
            "service.provider_session, service.owner_control, service.order_entry "
            "(submit/cancel), service.order_query, service.risk_query, service.monitor_query",
        )
        record_property(
            "i52_a2_requested_operations",
            "account.snapshot; market.subscribe/unsubscribe/snapshot/head/read_after/history "
            "(6 client requests; market.bootstrap_many is Host capability only)",
        )
        record_property(
            "i52_a2_not_exercised",
            "account.snapshot, market.subscribe, market.unsubscribe, subscriber creation, "
            "provider polling/history, and all order writes",
        )
    finally:
        if owner is not None and owner.state != "closed":
            try:
                owner.close()
            except Exception as exc:
                cleanup_failures.append(f"sdk_owner_close:{type(exc).__name__}")
        children = tuple(record for record, _, _ in owned_children.values())
        for child_record in children:
            reap_owned_child(child_record)
        cleanup_problem = (
            any(
                not record["closed"] or record.get("observed_exitcode") is None
                for record in children
            )
            or bool(forced_cleanup)
            or bool(cleanup_failures)
        )
        if cleanup_problem:
            import sys

            active_error = sys.exc_info()[1]
            if active_error is None:
                raise AssertionError(
                    "I52-A2 synthetic control-plane child exit was not confirmed as normal: "
                    f"forced={tuple(forced_cleanup)}, failures={tuple(cleanup_failures)}"
                )
            try:
                active_error.i52_a2_cleanup_failures = (
                    tuple(forced_cleanup),
                    tuple(cleanup_failures),
                )
            except Exception:
                pass
