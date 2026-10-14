"""Local-process evidence for the service-backed managed execution adapter.

A real execution service process runs on this machine, and the adapter is
driven through a real SDK client runtime over real CURVE transport while the
Backtrader Broker and Store project the framework order.  Only the account-data
provider and the keys are synthetic; the order route itself is the service.

The test is skipped when the optional service packages are not installed:
Backtrader must keep working without them.
"""

from __future__ import annotations

import multiprocessing
import socket
from contextlib import suppress
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
zmq = pytest.importorskip("zmq")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402

from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter  # noqa: E402

_DOMAIN = "paper:bt-service-execution"
_SERVICE_ID = "bt-execution-service"
_SERVICE_PRINCIPAL = "bt-execution-principal"
_INSTANCE_ID = "bt-execution-owner"
_SERVICE_SCOPE_REF = "bt-execution-root-v1"
_SERVER_SECURITY_REF = "bt-execution-server-curve-v1"
_ACCOUNT = "account-a"
_STRATEGY = "strategy-bt-a"
_PRINCIPAL = "bt-strategy-a-principal"
_ORDER_SCOPE_REF = "bt-strategy-orders-a-v1"
_QUERY_SCOPE_REF = "bt-strategy-order-query-a-v1"
_REQUEST_TIMEOUT_MS = 3000
_MAX_MESSAGE_BYTES = 65_536
_TRADING_DAY = "20261014"
_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


class _Provider:
    """Synthetic provider adapter owned by the service process."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: list[str] = []
        self.fail_next_submit = False

    def submit(self, intent):
        self.submitted.append(intent.intent_id)
        if self.fail_next_submit:
            self.fail_next_submit = False
            raise TimeoutError("synthetic provider timeout")
        return _observation(intent.intent_id)

    def cancel(self, intent):
        self.cancelled.append(intent.cancel_id)
        return _cancel_observation(intent)


def _observation(intent_id: str):
    from bt_api_execution import ProviderObservation

    return ProviderObservation.accepted(intent_id, "provider-order-1")


def _cancel_observation(intent):
    from bt_api_execution import CancelObservation

    return CancelObservation.accepted(
        intent.cancel_id, intent.target_intent_id, intent.provider_order_id
    )


class _Gate:
    """Synthetic admission gate covering both managed ports."""

    def __init__(self) -> None:
        self.reserved: list[str] = []

    def reserve(self, intent):
        reference = getattr(intent, "intent_id", None) or intent.cancel_id
        self.reserved.append(reference)
        return SimpleNamespace(permit_id=f"permit-{reference}")

    def validate(self, permit_id, intent):
        return SimpleNamespace(permit_id=permit_id)

    def claim_for_dispatch(self, permit_id, intent):
        return SimpleNamespace(permit_id=permit_id)

    def claim_before_dispatch(self, permit_id, intent):
        from bt_api_execution import CancelDispatchClaimReceiptV1

        return CancelDispatchClaimReceiptV1(
            permit_reference=permit_id,
            scope_key=intent.scope.key,
            cancel_id=intent.cancel_id,
            intent_fingerprint=intent.fingerprint,
        )

    def release(self, permit_id, reason):
        return None

    def settle(self, permit_id):
        return None


def _service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": "bt-execution-listener-v1",
        "registration_policy_ref": "bt-execution-registration-v1",
        "service_requirements_ref": "bt-execution-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "bt-execution-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _client_config(endpoint: str, security_ref: str) -> dict:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _ORDER_SCOPE_REF,
                            "transport_ref": "bt-execution-connect-v1",
                            "account_ref": _ACCOUNT,
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _QUERY_SCOPE_REF,
                            "transport_ref": "bt-execution-connect-v1",
                            "account_ref": _ACCOUNT,
                        },
                    ],
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "bt-execution-connect-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": security_ref,
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _host_process(control, raw_config, registry_path, keys, store_path):
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    provider = _Provider()
    gate = _Gate()
    store = None
    host = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-execution-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-execution-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-execution-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={keys["strategy_public"]: _PRINCIPAL},
            grants={
                _PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ORDER_SCOPE_REF,
                                _SCOPE,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_REF,
                                _SCOPE,
                                frozenset({"orders.query"}),
                            ),
                        ),
                    ),
                )
            },
        )
        execution_scope = ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY, _TRADING_DAY)
        store = SqliteExecutionStore(store_path)

        def resource_provider(component, _instance_id, _options, _scope):
            if component != "execution":
                raise AssertionError("unexpected service component")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {_SCOPE: execution_scope},
                    "dispatch": provider,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=25)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("close",):
                host.close()
                store.close()
                store = None
                control.send(("closed", host.state))
                return
            if command == ("counts",):
                control.send(
                    (
                        "counts",
                        tuple(provider.submitted),
                        tuple(provider.cancelled),
                        tuple(gate.reserved),
                    )
                )
                continue
            if command == ("fail_next_submit",):
                provider.fail_next_submit = True
                control.send(("armed",))
                continue
            raise AssertionError("unknown local execution host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        if store is not None:
            with suppress(BaseException):
                store.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _start_process(context, target, args, label):
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=target, args=(child, *args), name=label)
    process.start()
    child.close()
    return {"process": process, "pipe": parent, "label": label}


def _receive(pipe, timeout=20.0):
    assert pipe.poll(timeout), "spawned execution service missed its response bound"
    return pipe.recv()


def _managed_broker_info(intent_id: str) -> dict:
    return {
        "managed_order_type": "LIMIT",
        "managed_intent_id": intent_id,
        "managed_signal_id": "signal." + intent_id,
        "managed_instrument": "BTC-USDT",
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "fixture.metadata.v1",
        "managed_instrument_metadata_digest": "a" * 64,
        "offset": "open",
        "reduce_only": False,
    }


def test_backtrader_orders_route_through_a_real_execution_service(tmp_path):
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_execution import ServiceExecutionClient, ServiceExecutionError
    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    from tests.unit.brokers.test_btapibroker_managed_execution_projection import (
        _ResponseProvider,
        _make_started_stack,
    )

    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "strategy_public": strategy_public,
    }
    host = None
    runtime = None
    store = None
    try:
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "bt-execution-registry.sqlite3"),
                keys,
                str(tmp_path / "bt-execution.sqlite3"),
            ),
            "bt-execution-host",
        )
        ready = _receive(host["pipe"])
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint

        runtime = ServiceClientRuntime(
            parse_client_config(_client_config(endpoint, "bt-execution-curve-v1")),
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
            scope_resolver=lambda _ref: _SCOPE,
            peer_resolver=lambda _service: WireIdentity(
                WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {
                    "bt-execution-curve-v1": ClientCurveKeys(
                        server_public, strategy_public, strategy_secret
                    )
                }
            ),
        )
        assert runtime.start().degraded_count == 0

        client = ServiceExecutionClient(
            runtime,
            "broker.orders",
            scope_ref=_ORDER_SCOPE_REF,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_REF,
        )
        adapter = ServiceExecutionAdapter(client)
        provider = _ResponseProvider([])
        store, data, broker = _make_started_stack(None, provider, managed_execution_adapter=adapter)

        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info("intent-1"),
        )
        assert order.status == bt.Order.Accepted
        assert order.info.get("external_order_id") == "provider-order-1"
        counts = _command(host, "counts")
        assert counts[1] == ("intent-1",)
        # The legacy provider route stayed untouched.
        assert provider.submitted_orders == []

        # A repeated framework order with the same identity is not redispatched.
        duplicate = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info("intent-1"),
        )
        assert duplicate.info.get("external_order_id") == "provider-order-1"
        assert _command(host, "counts")[1] == ("intent-1",)

        # A provider failure is a durable UNKNOWN record and is not resent.
        assert _command(host, "fail_next_submit") == ("armed",)
        unknown = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_broker_info("intent-2"),
        )
        assert unknown.info.get("execution_unknown") is True
        assert unknown.alive() is True
        assert unknown.executed.size == pytest.approx(0.0)
        assert _command(host, "counts")[1] == ("intent-1", "intent-2")
        assert client.query("intent-2").state == "UNKNOWN"

        # Cancellation reaches the same account entry with the evidenced order.
        broker.cancel(order)
        assert _command(host, "counts")[2] == ("cancel.intent-1",)
        assert provider.cancelled_orders == []
        assert order.alive() is True

        # The durable facts survive the service being replaced.
        _close_host(host)
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "bt-execution-registry.sqlite3"),
                keys,
                str(tmp_path / "bt-execution.sqlite3"),
            ),
            "bt-execution-host-r2",
        )
        assert _receive(host["pipe"])[0] == "ready"
        # A restarted service has a new epoch: the borrowed runtime must
        # recover its registration before any business call, and the refusal
        # proves the old registration is not silently reused.
        with pytest.raises(ServiceExecutionError, match="STALE_EPOCH"):
            client.query("intent-1")
        assert runtime.recover().degraded_count == 0
        assert client.query("intent-1").state == "ACKED"
        assert client.query("intent-2").state == "UNKNOWN"
        # The replacement service dispatches nothing for durable facts.
        assert _command(host, "counts")[1] == ()
    finally:
        if store is not None:
            with suppress(Exception):
                store.stop()
        if runtime is not None:
            with suppress(Exception):
                runtime.close()
        if host is not None:
            _close_host(host)


def _command(host, *command):
    host["pipe"].send(command)
    result = _receive(host["pipe"])
    assert result[0] != "error", result
    return result


def _close_host(host):
    if host["pipe"].closed:
        return
    host["pipe"].send(("close",))
    assert _receive(host["pipe"], timeout=20.0)[0] == "closed"
    host["process"].join(20)
    if host["process"].is_alive():
        host["process"].terminate()
        raise AssertionError("spawned execution service did not exit normally")
    assert host["process"].exitcode == 0
    host["pipe"].close()
    host["process"].close()


def test_decimal_quantity_is_accepted_by_the_adapter():
    """The adapter passes exact decimal quantities through unchanged."""

    class _Client:
        def __init__(self):
            self.submitted = []

        def submit(self, **kwargs):
            self.submitted.append(kwargs)
            return SimpleNamespace(
                state="ACKED",
                intent_id=kwargs["intent_id"],
                provider_order_id="provider-order-1",
                dispatch_attempts=1,
            )

        def cancel(self, **kwargs):  # pragma: no cover - not used here
            raise AssertionError("cancel is not expected")

    client = _Client()
    adapter = ServiceExecutionAdapter(client)
    from tests.unit.stores.test_service_execution_adapter import _StubOrder, _legacy_dispatch

    order = _StubOrder(
        exectype=bt.Order.Limit,
        size=Decimal("2.5"),
        price=Decimal("101.5"),
        info={
            "managed_intent_id": "intent-decimal",
            "managed_signal_id": "signal.intent-decimal",
            "managed_instrument": "BTC-USDT",
            "managed_position_effect": "OPEN",
        },
    )

    response = adapter.submit_order(order, _legacy_dispatch)

    assert response["status"] == "accepted"
    assert client.submitted[0]["quantity"] == Decimal("2.5")
    assert client.submitted[0]["price"] == Decimal("101.5")
