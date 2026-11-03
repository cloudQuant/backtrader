"""Iteration 60 R2-E: a real local CURVE service host that owns a strategy ledger.

The host is a spawned SDK ``ServiceHost`` whose execution ``account_owner``
component is configured with ``command_bindings`` (typed orders) and the
``strategy_ledger`` option (explicit SQLite path, budgets, capital, terms).
The trusted resources are a temp ``SqliteExecutionStore``, a synthetic
provider and a subscription-fed ``StreamedAccountPositions``. The parent test
drives the provider (fills, fees, terminal states) and the position
subscription through a control pipe; everything else crosses CURVE-
authenticated ZMQ sockets. INTEGRATION_SIM: no real account, provider or
network.
"""

from __future__ import annotations

import multiprocessing
import socket
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

DOMAIN = "sim:bt-r2e-ledger"
SERVICE_ID = "bt-r2e-execution"
SERVICE_PRINCIPAL = "bt-r2e-execution-principal"
INSTANCE_ID = "bt-r2e-owner"
ACCOUNT = "bt-r2e-account"
STRATEGY = "bt-r2e-strategy"
PRINCIPAL = "bt-r2e-strategy-principal"
INSTRUMENT = "BTC-USDT"
ORDER_SCOPE_REF = "bt-r2e-orders-v1"
QUERY_SCOPE_REF = "bt-r2e-order-query-v1"
TRANSPORT_REF = "bt-r2e-rpc-v1"
SERVER_SECURITY_REF = "bt-r2e-server-v1"
CLIENT_SECURITY_REF = "bt-r2e-client-v1"
ORDER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
QUERY_OPERATIONS = frozenset({"orders.query", "execution.account_books.query"})


def wire_scope() -> Any:
    from bt_api_base.service_protocol import WireScope

    return WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY)


def declaration() -> dict[str, Any]:
    """The typed command-binding declaration shared by host and client config."""

    return {
        "binding_schema_version": 1,
        "account_key": {
            "provider": "sim",
            "venue": "sim",
            "environment": "simulation",
            "account_id": ACCOUNT,
        },
        "instruments": [
            {
                "provider": "sim",
                "venue": "sim",
                "environment": "simulation",
                "product_type": "spot",
                "instrument_id": INSTRUMENT,
                "native_symbol": INSTRUMENT,
            }
        ],
        "quantity_unit": "base",
        "price_currency": "USDT",
    }


def ledger_option(directory: Path, **changes: Any) -> dict[str, Any]:
    option: dict[str, Any] = {
        "path": str(directory / "strategy-ledger.sqlite3"),
        "instruments": {INSTRUMENT: {"multiplier": "1", "quote_currency": "USDT"}},
        "budgets": {STRATEGY: {"limit": "200000", "currency": "USDT"}},
        "capital": {STRATEGY: {"amount": "200000", "currency": "USDT"}},
    }
    option.update(changes)
    return option


def endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def service_config(rpc_endpoint: str, ledger: Any) -> dict[str, Any]:
    options: dict[str, Any] = {"role": "account_owner", "command_bindings": [declaration()]}
    if ledger is not None:
        options["strategy_ledger"] = ledger
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": SERVICE_ID,
        "scope_ref": "bt-r2e-service-v1",
        "transport_ref": "bt-r2e-listener-v1",
        "registration_policy_ref": "bt-r2e-registration-v1",
        "service_requirements_ref": "bt-r2e-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": options,
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "bt-r2e-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": rpc_endpoint},
                    "security_profile_ref": SERVER_SECURITY_REF,
                    "options": {"high_water_mark": 32, "max_message_bytes": 262_144},
                }
            },
        },
    }


def client_config(rpc_endpoint: str) -> dict[str, Any]:
    def route(mount: str, scope_ref: str) -> dict[str, Any]:
        return {
            "mount": mount,
            "service_id": SERVICE_ID,
            "instance_id": INSTANCE_ID,
            "scope_ref": scope_ref,
            "transport_ref": TRANSPORT_REF,
            "account_ref": ACCOUNT,
        }

    writer = route("broker.orders", ORDER_SCOPE_REF)
    writer["command_binding"] = declaration()
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": STRATEGY},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {"bindings": [writer, route("broker.order_query", QUERY_SCOPE_REF)]},
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": rpc_endpoint},
                    "security_profile_ref": CLIENT_SECURITY_REF,
                }
            },
        },
    }


class _Provider:
    """Synthetic provider: accepts orders; later fills arrive via ``fill``."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.sink: Any = None

    def attach_observation_sink(self, sink: Any) -> None:
        self.sink = sink

    def submit(self, intent: Any) -> Any:
        from bt_api_execution import ProviderObservation

        self.submitted.append(intent.intent_id)
        return ProviderObservation.accepted(intent.intent_id, "provider-" + intent.intent_id)

    def cancel(self, intent: Any) -> Any:
        from bt_api_execution import CancelObservation

        return CancelObservation.accepted(
            intent.cancel_id, intent.target_intent_id, intent.provider_order_id
        )

    def fill(self, intent_id: str, state: str, filled: str, price: str | None, fee: str | None):
        from bt_api_execution import ExecutionState, ProviderObservation

        observation = ProviderObservation(
            intent_id=intent_id,
            state=ExecutionState(state),
            provider_order_id="provider-" + intent_id,
            filled_quantity=Decimal(filled),
            average_price=None if price is None else Decimal(price),
            cumulative_commission=None if fee is None else Decimal(fee),
            cumulative_commission_currency=None if fee is None else "USDT",
        )
        record = self.sink(wire_scope(), observation)
        return record.state.value


def serve(control: Any, rpc_endpoint: str, directory: str, keys: dict, ledger: Any, mode: str):
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_execution import ExecutionScope, SqliteExecutionStore

    from bt_api_py.account_position_stream import StreamedAccountPositions
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    provider = _Provider()
    stream = StreamedAccountPositions(ACCOUNT, "sim:account-position-stream")
    stream.apply_snapshot({})
    store = None
    host = None
    scope = wire_scope()
    try:
        config = parse_service_config(service_config(rpc_endpoint, ledger))
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, SERVICE_PRINCIPAL, SERVICE_ID),
            scope=WireScope(DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-r2e-scope-v1",
            security_ref=SERVER_SECURITY_REF,
            security_version="curve-local-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-r2e-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-r2e-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={keys["strategy_public"]: PRINCIPAL},
            grants={
                PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, PRINCIPAL, STRATEGY),
                        (
                            ResourceGrant(
                                INSTANCE_ID,
                                "service.order_entry",
                                ORDER_SCOPE_REF,
                                scope,
                                ORDER_OPERATIONS,
                            ),
                            ResourceGrant(
                                INSTANCE_ID,
                                "service.order_query",
                                QUERY_SCOPE_REF,
                                scope,
                                QUERY_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
        )
        store = SqliteExecutionStore(str(Path(directory) / "execution.sqlite3"))
        execution_scope = ExecutionScope("SIM", "simulation", ACCOUNT, STRATEGY, "20261104")

        def resource_provider(component: str, *_args: Any) -> Any:
            if component != "execution":
                raise RuntimeError("UNEXPECTED_COMPONENT")
            values = {
                "store": store,
                "targets": {scope: execution_scope},
                "dispatch": provider,
                "admission": {"allow_unprotected": True},
            }
            if ledger is not None and mode != "no_positions":
                values["strategy_ledger_positions"] = stream
            return ComponentResources.borrowed(values, ready=lambda: True)

        host = ServiceHost(
            config, authority, str(Path(directory) / "registry.sqlite3"), resource_provider
        )
        host.start()
        control.send(("ready", host.endpoint))
        while True:
            host.serve_once(timeout_ms=20)
            if not control.poll(0):
                continue
            message = control.recv()
            command = message[0]
            try:
                if command == "close":
                    host.close()
                    control.send(("closed", list(provider.submitted)))
                    return
                if command == "fill":
                    control.send(("ok", provider.fill(*message[1:])))
                elif command == "positions":
                    stream.apply_snapshot(
                        {(name, "net"): Decimal(qty) for name, qty in message[1].items()}
                    )
                    control.send(("ok", None))
                elif command == "interrupt":
                    stream.mark_interrupted("SUBSCRIPTION_DISCONNECTED")
                    control.send(("ok", None))
                else:
                    control.send(("error", "UNKNOWN_COMMAND"))
            except Exception as error:  # reported to the parent as a finite code
                code = getattr(error, "code", None)
                control.send(("error", code if type(code) is str else type(error).__name__))
    except BaseException as error:  # pragma: no cover - reported to the parent
        code = getattr(error, "code", None)
        try:
            control.send(("error", code if type(code) is str else type(error).__name__))
        except Exception:
            pass
        if host is not None and host.state not in {"closed", "failed"}:
            try:
                host.close()
            except BaseException:
                pass
    finally:
        if store is not None:
            store.close()
        control.close()


class Host:
    """The spawned service host and its control pipe."""

    def __init__(self, directory: Path, *, ledger: Any = "default", mode: str = "normal"):
        import zmq

        self.keys = {}
        self.keys["server_public"], self.keys["server_secret"] = zmq.curve_keypair()
        self.keys["strategy_public"], self.keys["strategy_secret"] = zmq.curve_keypair()
        self.endpoint = endpoint()
        if ledger == "default":
            ledger = ledger_option(directory)
        context = multiprocessing.get_context("spawn")
        self.pipe, child = context.Pipe(duplex=True)
        self.process = context.Process(
            target=serve,
            args=(child, self.endpoint, str(directory), self.keys, ledger, mode),
            name="bt-r2e-ledger-host",
        )
        self.process.start()
        child.close()
        if not self.pipe.poll(90.0):
            self.kill()
            raise AssertionError("host start timeout")
        self.ready = self.pipe.recv()

    def command(self, *message: Any) -> Any:
        self.pipe.send(message)
        assert self.pipe.poll(60.0), "host command timeout"
        reply = self.pipe.recv()
        assert reply[0] == "ok", reply
        return reply[1]

    def close(self) -> list[str]:
        self.pipe.send(("close",))
        assert self.pipe.poll(60.0), "host close timeout"
        result = self.pipe.recv()
        self.process.join(30.0)
        assert result[0] == "closed", result
        assert self.process.exitcode == 0
        return result[1]

    def kill(self) -> None:
        self.process.join(1.0)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(5.0)


def runtime_factory(keys: dict):
    from bt_api_base.service_protocol import WireIdentity, WireRole

    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    def factory(config: Any) -> Any:
        return ServiceClientRuntime(
            config,
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, PRINCIPAL, STRATEGY),
            scope_resolver=lambda reference: {
                ORDER_SCOPE_REF: wire_scope(),
                QUERY_SCOPE_REF: wire_scope(),
            }[reference],
            peer_resolver=lambda _service_id: WireIdentity(
                WireRole.SERVICE, SERVICE_PRINCIPAL, SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {
                    CLIENT_SECURITY_REF: ClientCurveKeys(
                        keys["server_public"], keys["strategy_public"], keys["strategy_secret"]
                    )
                }
            ),
            run_id="bt-r2e-run-" + uuid.uuid4().hex[:8],
            requested_operations={
                "broker.orders": ORDER_OPERATIONS,
                "broker.order_query": QUERY_OPERATIONS,
            },
        )

    return factory
