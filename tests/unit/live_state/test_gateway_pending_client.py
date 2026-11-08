"""Offline SDK client + BT durable host against a synthetic CURVE Gateway."""

from __future__ import annotations

import queue
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import zmq
from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
from bt_api_gateway.session_guard import LocalAccountSessionGuard

from backtrader.live_state.gateway_pending import GatewayPendingHost
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_direct_client import (
    GatewayClientRoute,
    GatewayDirectClient,
    build_gateway_order_intent,
)
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import (
    GatewayDirectGrant,
    GatewayDirectServiceBinding,
    recovery_requested_operations,
)
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
from bt_api_py.service_runtime_thread import ThreadedServiceClientRuntime

DOMAIN, ACCOUNT = "paper:demo", "synthetic-account"
SERVICE = WireIdentity(WireRole.SERVICE, "gateway-principal", "gateway-service")
CLIENT = WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a")
OPS = frozenset({"direct.reserve", "direct.release", "direct.command_status", "direct.dispatch"})


def _endpoint():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return "tcp://127.0.0.1:" + str(sock.getsockname()[1])


def _service_config(endpoint):
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": SERVICE.actor_ref,
            "scope_ref": "scope-a",
            "transport_ref": "server-transport",
            "registration_policy_ref": "direct-policy-v1",
            "service_requirements_ref": "direct-requirements-v1",
            "components": {
                "gateway": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": "gateway-a",
                        "bind_ports": ["service.direct_write"],
                        "options": {"role": "trading_owner", "dispatch_enabled": True},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "server-transport": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": "security-a",
                    }
                },
            },
        }
    )


def _client_config(endpoint):
    return parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": CLIENT.actor_ref},
            "clients": {
                "gateway": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.direct_write",
                                "service_id": SERVICE.actor_ref,
                                "instance_id": "gateway-a",
                                "scope_ref": "scope-a",
                                "account_ref": ACCOUNT,
                                "transport_ref": "client-transport",
                            }
                        ],
                        "options": {"request_timeout_ms": 2000},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "client-transport": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": "security-a",
                    }
                },
            },
        }
    )


@contextmanager
def _gateway(tmp_path):
    endpoint = _endpoint()
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    scope = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT.actor_ref)
    resource = ResourceGrant("gateway-a", "service.direct_write", "scope-a", scope, OPS)
    authority = TrustedServiceAuthority(
        identity=SERVICE,
        scope=WireScope(DOMAIN),
        scope_ref="scope-a",
        scope_version="scope-v1",
        security_ref="security-a",
        security_version="security-v1",
        registration_policy_ref="direct-policy-v1",
        registration_policy_version="direct-policy-v1",
        service_requirements_ref="direct-requirements-v1",
        service_requirements_version="direct-requirements-v1",
        curve_public_key=server_keys[0],
        curve_secret_key=server_keys[1],
        principals={client_keys[0]: CLIENT.principal_ref},
        grants={CLIENT.principal_ref: (PrincipalGrant(CLIENT, (resource,)),)},
    )
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    ready, sends = queue.Queue(), queue.Queue()
    stop = threading.Event()

    def serve():
        owner = host = None
        try:
            journals = []

            def owner_factory():
                guard = LocalAccountSessionGuard(guard_dir, ACCOUNT, "synthetic-owner")
                generation = guard.acquire()
                journal = GatewayDirectCommandJournal.create(
                    tmp_path / "journal.sqlite", ACCOUNT, generation=generation
                )
                journals.append(journal)

                def native(payload, port, host_scope):
                    key = payload["idempotency_key"]
                    identity = NativeOrderIdentity(
                        "TEST", "native-" + key, {"inst_id": "rb", "trading_day": "20300101"}, 1
                    )
                    record = PreDispatchRecord(
                        operation=WriteOperation.PLACE,
                        host_scope=host_scope,
                        exchange_name="TEST",
                        symbol=payload["symbol"],
                        identity=identity,
                        target_identity=None,
                        request_summary=payload,
                        trading_day="20300101",
                        session_generation=1,
                        created_at_utc="synthetic",
                    )
                    marker = port.commit(record)
                    if marker is None:
                        return NativeDispatchOutcome(False, identity, None)
                    sends.put(key)
                    return NativeDispatchOutcome(True, identity, marker)

                dispatcher = GatewayDirectDispatcher(
                    journal,
                    "TEST",
                    guard,
                    native,
                    lambda identity: ("TEST:" + identity.client_order_id,),
                    lambda _: True,
                )
                return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

            owner = GatewayDirectOwner(
                owner_factory, queue_size=8, max_queue_wait_seconds=10, busy_timeout_seconds=10
            )
            if not owner.start(10):
                raise RuntimeError("OWNER_START_FAILED")
            journal = journals[0]
            binding = GatewayDirectServiceBinding(
                journal,
                {CLIENT.principal_ref: GatewayDirectGrant(CLIENT.actor_ref, frozenset({"rb"}))},
                owner=owner,
            )
            host = ServiceHost(
                _service_config(endpoint),
                authority,
                tmp_path / "registry.sqlite",
                lambda *_: ComponentResources.borrowed({"binding": binding}, ready=lambda: True),
            )
            host.start()
            ready.put(("ready", journal.journal_id))
            while not stop.is_set():
                host.serve_once(10)
        except BaseException as exc:
            ready.put(("error", type(exc).__name__, getattr(exc, "code", None)))
        finally:
            try:
                if host is not None and host.state == "started":
                    host.close()
                if owner is not None and not owner.close(10):
                    raise RuntimeError("OWNER_CLOSE_FAILED")
                ready.put(("closed",))
            except BaseException as exc:
                ready.put(("cleanup_error", type(exc).__name__))

    thread = threading.Thread(target=serve, name="synthetic-gateway")
    thread.start()
    runtimes = []
    dropped = set()
    try:
        result = ready.get(timeout=15)
        assert result[0] == "ready", result
        binding = GatewayCommandBinding(result[1], ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)

        def connect(run_id, *, recovery=False):
            route = GatewayClientRoute(
                "broker.direct_write",
                SERVICE.actor_ref,
                "gateway-a",
                "scope-a",
                WireScope(
                    DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT.actor_ref, run_id=run_id
                ),
                CLIENT,
            )

            def factory():
                raw = ZmqTransportFactory(
                    {"security-a": ClientCurveKeys(server_keys[0], *client_keys)}
                )

                class Drop:
                    def __init__(self, wrapped):
                        self.wrapped = wrapped

                    def request(self, request, *, timeout):
                        response = self.wrapped.request(request, timeout=timeout)
                        operation = request.header.operation
                        if operation in dropped:
                            dropped.remove(operation)
                            raise TimeoutError("synthetic lost response")
                        return response

                    def close(self):
                        self.wrapped.close()

                return ServiceClientRuntime(
                    _client_config(endpoint),
                    identity=CLIENT,
                    scope_resolver=lambda _: WireScope(DOMAIN, account_ref=ACCOUNT),
                    peer_resolver=lambda _: SERVICE,
                    transport_factory=lambda *args: Drop(raw(*args)),
                    run_id=run_id,
                    requested_operations=recovery_requested_operations() if recovery else None,
                )

            runtime = ThreadedServiceClientRuntime(factory)
            runtimes.append(runtime)
            runtime.start(timeout_seconds=10)
            return runtime, route

        yield binding, connect, sends, dropped
    finally:
        errors = []
        for runtime in reversed(runtimes):
            try:
                runtime.close(timeout_seconds=10)
            except Exception as exc:
                errors.append(type(exc).__name__)
        stop.set()
        thread.join(15)
        if thread.is_alive():
            errors.append("host thread did not stop")
        else:
            try:
                closed = ready.get(timeout=3)
                if closed != ("closed",):
                    errors.append(str(closed))
            except queue.Empty:
                errors.append("missing cleanup confirmation")
        assert not errors, errors


def _request(key):
    return OrderRequest(
        symbol="rb",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("10"),
        account_id=ACCOUNT,
        client_order_id="client-" + key,
        idempotency_key=key,
    )


def _sent(client, key):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.status(key, timeout_seconds=5)
        if result.record is not None and result.record.state == "SENT":
            return result.record
        time.sleep(0.02)
    pytest.fail("synthetic Gateway did not reach SENT")


@pytest.mark.parametrize("recovery_run", ["run-old", "run-new"])
def test_gateway_client_with_bt_pending_host_recovery(tmp_path, state, monkeypatch, recovery_run):
    """Reply loss and failed local writes retain durable original identities."""
    import json

    import backtrader.live_state.pending as pending_module

    with _gateway(tmp_path) as (binding, connect, sends, dropped):
        host = GatewayPendingHost.upgrade_for_gateway(
            state.strategy_dir, state.strategy_uuid, binding
        )
        runtime, route = connect("run-old")
        client = GatewayDirectClient(runtime, binding=binding, route=route, host=host)
        dropped.add("direct.reserve")
        assert (
            client.reserve(_request("one"), ttl_seconds=25, timeout_seconds=5).outcome == "UNKNOWN"
        )
        assert host.load_intent("one").ttl_seconds == 25
        first = client.status("one")
        assert first.outcome == "OBSERVED" and first.record.state == "RESERVED"
        second = client.reserve(_request("two"), ttl_seconds=20)
        assert second.outcome == "OBSERVED" and second.record.state == "RESERVED"
        assert {item.request_key for item in host.list_intents()} == {"one", "two"}
        assert first.record.native_identity is second.record.native_identity is None
        assert (
            client.reserve(_request("one"), ttl_seconds=30).record.reservation_id
            == first.record.reservation_id
        )
        assert host.load_intent("one").ttl_seconds == 25

        other_marker = host.commit_pre_dispatch("one", first.record)
        marker = host.commit_pre_dispatch("two", second.record)
        assert marker != other_marker
        reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        assert reopened.commit_pre_dispatch("two", reopened.load_record("two")) == marker
        assert reopened.commit_pre_dispatch("one", reopened.load_record("one")) == other_marker
        client = GatewayDirectClient(runtime, binding=binding, route=route, host=reopened)
        dropped.add("direct.dispatch")
        dispatched = client.dispatch("two")
        assert dispatched.outcome == "UNKNOWN" and dispatched.marker_id == marker
        assert sends.get(timeout=5) == "two"
        path = Path(state.pending.path)
        before_identity_write = path.read_bytes()
        with monkeypatch.context() as patch:

            def fail_identity_write(*_args, **_kwargs):
                raise OSError("synthetic record write failure")

            patch.setattr(pending_module, "atomic_write_json", fail_identity_write)
            failed_observation = client.status("two")
        assert failed_observation.outcome == "UNKNOWN"
        assert failed_observation.code == "INVALID_REPLY_OR_HOST_FAILURE"
        assert path.read_bytes() == before_identity_write
        assert reopened.load_record("two").native_identity is None
        sent = _sent(client, "two")
        assert sent.native_identity.client_order_id == "native-two"
        reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        assert reopened.load_record("two") == sent
        data = json.loads(Path(state.pending.path).read_text())
        entry = data["gateway"]["intents"]["two"]
        assert entry["marker_id"] == marker
        linked = data["active"][marker]
        assert entry["record"]["native_identity"] == sent.native_identity.to_dict()
        assert linked["client_order_id"] == sent.native_identity.client_order_id
        assert linked["native_identity"] == dict(sent.native_identity.fields)
        assert client.dispatch("two").outcome != "QUEUED"
        with pytest.raises(queue.Empty):
            sends.get(timeout=0.2)

        client = GatewayDirectClient(runtime, binding=binding, route=route, host=reopened)
        third = client.reserve(_request("three"), ttl_seconds=20)
        assert third.outcome == "OBSERVED" and third.record.state == "RESERVED"
        path = Path(state.pending.path)
        before = path.read_bytes()
        with monkeypatch.context() as patch:

            def fail_write(*_args, **_kwargs):
                raise OSError("synthetic local write failure")

            patch.setattr(pending_module, "atomic_write_json", fail_write)
            failed = client.dispatch("three")
        assert failed.outcome == "TRANSPORT_NOT_STARTED" and failed.code == "DISPATCH_NOT_COMMITTED"
        assert path.read_bytes() == before
        assert reopened.load_record("three").native_identity is None
        with pytest.raises(queue.Empty):
            sends.get(timeout=0.2)
        runtime.close(timeout_seconds=10)
        runtime2, route2 = connect(recovery_run, recovery=True)
        restarted = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        newer = GatewayDirectClient(runtime2, binding=binding, route=route2, host=restarted)
        assert newer.dispatch("one").code == "ROUTE_UNAVAILABLE"
        assert newer.reserve(_request("four")).code == "ROUTE_UNAVAILABLE"
        assert restarted.load_intent("four") is None
        if recovery_run == "run-new":
            unrelated_route = replace(route2, scope=replace(route2.scope, run_id="run-other"))
            restarted.save_intent(
                build_gateway_order_intent(binding, unrelated_route, _request("other"))
            )
            assert newer.status("other").code == "ROUTE_UNAVAILABLE"
            assert newer.release("other", operation_id="release-other").code == "ROUTE_UNAVAILABLE"
            assert restarted.load_release("other") is None
        recovery_status = newer.status("one")
        assert recovery_status.record is not None, (
            recovery_status,
            [(item.scope.run_id, item.operations) for item in runtime2.status().bindings],
        )
        assert recovery_status.record.reservation_id == first.record.reservation_id
        dropped.add("direct.release")
        release = newer.release("one", operation_id="release-one")
        assert release.outcome == "UNKNOWN"
        planned = restarted.load_release("one")
        assert (
            planned.operation_id == "release-one"
            and planned.expected_version == first.record.version
        )
        reloaded = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        assert reloaded.load_release("one") == planned
        newer = GatewayDirectClient(runtime2, binding=binding, route=route2, host=reloaded)
        result = newer.release("one", operation_id="release-one")
        assert result.outcome == "OBSERVED" and result.record.state == "RELEASED"
        assert reloaded.load_intent("one").ttl_seconds == 25
        with pytest.raises(queue.Empty):
            sends.get(timeout=0.2)
