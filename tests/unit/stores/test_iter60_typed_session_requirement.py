"""Iteration 60 R2-B: a managed BT session requires typed order commands.

``run_configured_cerebro`` assembles the SDK execution client from the client
config; a ``broker.orders`` route without ``command_binding`` refuses before
any runtime is created, and a hand-built assembly whose client has no command
binding is refused by ``ServiceExecutionSession`` (no generic fallback).
UNIT: no service, provider or network.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.service_execution_assembly")

from bt_api_py.service_execution_assembly import (  # noqa: E402
    ServiceExecutionAssembly,
    ServiceExecutionRoutePlan,
)

import backtrader as bt  # noqa: E402
from backtrader.service.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
    ServiceExecutionSessionConfigError,
    run_configured_cerebro,
)


def _client_config():
    def route(mount, scope_ref):
        return {
            "mount": mount,
            "service_id": "execution-service",
            "instance_id": "execution-owner",
            "scope_ref": scope_ref,
            "transport_ref": "rpc-v1",
            "account_ref": "account-a",
        }

    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": "strategy-a"},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        route("broker.orders", "orders-v1"),
                        route("broker.order_query", "order-query-v1"),
                    ]
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "rpc-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": "tcp://127.0.0.1:1"},
                    "security_profile_ref": "client-curve-v1",
                }
            },
        },
    }


def test_configured_cerebro_refuses_a_writer_route_without_command_binding():
    created = []

    def factory(config):
        created.append(config)
        raise AssertionError("no runtime may be created")

    with pytest.raises(ServiceExecutionSessionConfigError) as error:
        run_configured_cerebro(bt.Cerebro(), _client_config(), runtime_factory=factory)
    assert error.value.code == "COMMAND_BINDING_REQUIRED"
    assert created == []


class _BindingLessClient:
    typed_commands = False


def test_session_refuses_an_assembly_whose_client_is_not_typed():
    routes = ServiceExecutionRoutePlan(
        writer_mount="broker.orders",
        writer_scope_ref="orders-v1",
        query_mount="broker.order_query",
        query_scope_ref="order-query-v1",
    )
    assembly = ServiceExecutionAssembly(
        object(),  # type: ignore[arg-type]  # refused before the runtime is used
        execution_client=_BindingLessClient(),  # type: ignore[arg-type]
        routes=routes,
    )
    with pytest.raises(ServiceExecutionSessionConfigError) as error:
        ServiceExecutionSession(assembly)
    assert error.value.code == "COMMAND_BINDING_REQUIRED"
