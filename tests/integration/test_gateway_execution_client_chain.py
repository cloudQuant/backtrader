"""Local client-chain integration; no venue, account, or Execution authority.

The Gateway is the existing SDK ServiceHost fixture. Risk and Execution are
synthetic authenticated CURVE peers: the latter reports only local receipt.
The market qualification seam supplies a synthetic value, not a market proof.
"""
from __future__ import annotations

import copy
import hashlib
import multiprocessing
import queue
import sqlite3
import threading
import time
from pathlib import Path

import pytest
import yaml

zmq = pytest.importorskip("zmq")
pytest.importorskip("msgpack")

import backtrader as bt
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.stores.btapistore import BtApiStore
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.service_protocol import (WIRE_PROTOCOL_VERSION, WireIdentity, WireRole,
                                          encode_wire_value, wire_contract_digest)
from bt_api_py.execution_parent_grant import OPERATIONS as EXEC_OPS, QUERY, SUBMIT
from bt_api_py.execution_routing import ExecutionRoutingOutcome
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_py.service_runtime_thread import ThreadedRuntimeError
from bt_api_transport_zmq.server import CurveServerCredentials
from bt_api_transport_zmq.service_v2 import ZmqServiceServer
from tests.integration import test_iter64_gateway_risk_process as gateway
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework
from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order, deliver
from tests.unit.live_state.test_gateway_execution_route_binding import CONFIG


class SyntheticPeer:
    def __init__(self, name, keys, client_public, handler, *, available=True):
        self.name, self.keys, self.client_public, self.handler = name, keys, client_public, handler
        self.available = available
        self.calls, self.errors = [], queue.Queue()
        self.ready, self.stop = queue.Queue(), threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        self.endpoint = self.ready.get(timeout=10)
        assert self.endpoint is not None

    def _serve(self):
        server = None
        try:
            peer = WireIdentity(WireRole.SERVICE, self.name + "-principal", self.name)
            def handle(principal, request):
                assert principal == gateway.STRATEGY.principal_ref
                op = request.header.operation
                self.calls.append(op)
                if op == "service.discover":
                    port = "service.execution_parent" if self.name == "execution" else "service.risk_order"
                    operations = sorted(EXEC_OPS) if self.name == "execution" else RISK_OPS
                    result = {"protocol_version": WIRE_PROTOCOL_VERSION, "wire_contract": wire_contract_digest(),
                              "service_id": self.name, "ready": self.available, "capabilities": [{
                                  "instance_id": self.name + "-instance", "port": port,
                                  "operations": operations}]}
                elif op == "service.register":
                    operations = sorted(EXEC_OPS) if self.name == "execution" else RISK_OPS
                    assert set(request.payload["operations"]) == set(operations)
                    result = {"registration_id": self.name + "-registration", "service_epoch": "epoch",
                              "operations": operations, "expires_at": time.time() + 120,
                              "lease_remaining_seconds": 120, "policy_version": "policy",
                              "requirements_version": "requirements"}
                elif op == "service.unregister":
                    result = {"unregistered": True, "registration_id": self.name + "-registration"}
                else:
                    result = self.handler(op, request)
                return {"ok": True, "code": "OK", "result": result}
            server = ZmqServiceServer("tcp://127.0.0.1:*", peer,
                {self.client_public: gateway.STRATEGY.principal_ref}, handle,
                credentials=CurveServerCredentials(*self.keys))
            self.ready.put(server.endpoint)
            while not self.stop.is_set():
                server.serve_once(timeout_ms=20)
        except BaseException as error:
            self.errors.put(error)
            self.ready.put(None)
        finally:
            if server is not None:
                server.close()

    def close(self):
        self.stop.set()
        self.thread.join(10)
        assert not self.thread.is_alive()
        if not self.errors.empty():
            raise self.errors.get_nowait()


RISK_OPS = ["risk.order.reserve", "risk.order.dispatch", "risk.order.release",
            "risk.order.status", "risk.status"]


def _raw(endpoint, exec_endpoint, risk_endpoint, journal):
    example = Path(__file__).resolve().parents[3] / "bt_api_py/examples/services/gateway-strategy-client.example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    raw["exchange_name"] = gateway.ROUTE
    raw["binding"] = dict(journal_id=journal, account_scope=gateway.ACCOUNT,
                          strategy_scope=gateway.STRATEGY.actor_ref, principal=gateway.STRATEGY.principal_ref)
    scope = dict(execution_domain_ref=gateway.DOMAIN, account_ref=gateway.ACCOUNT, account_refs=[],
                 strategy_ref=gateway.STRATEGY.actor_ref, run_id=gateway.RUN, manual_book_ref=None,
                 portfolio_ref=None, group_id=None, leg_id=None)
    identity = dict(role="strategy_client", principal_ref=gateway.STRATEGY.principal_ref,
                    actor_ref=gateway.STRATEGY.actor_ref, delegate_ref=None)
    route = dict(mount="broker.direct_write", service_id=gateway.SERVICE.actor_ref,
                 instance_id="gateway-a", scope_ref="scope-a", scope=scope, identity=identity)
    raw["route"] = route
    raw["peer"] = dict(role="service", principal_ref=gateway.SERVICE.principal_ref,
                       actor_ref=gateway.SERVICE.actor_ref, delegate_ref=None)
    raw["requested_operations"] = sorted(gateway._strategy_ops())
    raw["execution_time_policy"]["route"] = gateway.ROUTE
    raw["instruments_by_ref"] = {"rb": gateway.INSTRUMENT.to_dict()}
    raw.pop("market_settings")
    client = raw["client_config"]
    client["registration"]["strategy_ref"] = gateway.STRATEGY.actor_ref
    client["clients"]["gateway"]["settings"]["bindings"] = [dict(
        mount="broker.direct_write", service_id=gateway.SERVICE.actor_ref, instance_id="gateway-a",
        scope_ref="scope-a", account_ref=gateway.ACCOUNT, transport_ref="transport")]
    client["communication"]["profiles"]["transport"]["endpoints"] = {"rpc_connect": endpoint}
    def profile(endpoint, security):
        return dict(backend="zmq", config_schema_version=1, endpoints={"rpc_connect": endpoint},
                    security_profile_ref=security)
    risk_route = dict(mount="broker.risk_order", service_id="risk", instance_id="risk-instance",
                      scope_ref="risk-scope", scope=copy.deepcopy(scope), identity=copy.deepcopy(identity))
    risk_client = dict(client_config_schema_version=1, process_role="strategy_client",
        registration={"strategy_ref": gateway.STRATEGY.actor_ref},
        clients={"risk": {"config_schema_version": 1, "settings": {"bindings": [dict(
            mount="broker.risk_order", service_id="risk", instance_id="risk-instance", scope_ref="risk-scope",
            account_ref=gateway.ACCOUNT, transport_ref="risk-transport")]}}},
        communication={"config_schema_version": 1, "profiles": {"risk-transport": profile(risk_endpoint, "risk-security")}})
    raw["risk"] = dict(client_config=risk_client, route=risk_route, peer=dict(
        role="service", principal_ref="risk-principal", actor_ref="risk", delegate_ref=None),
        requested_operations=RISK_OPS)
    joint = copy.deepcopy(client)
    joint["clients"]["execution"] = {"config_schema_version": 1, "settings": {"bindings": [dict(
        mount="broker.execution_parent", service_id="execution", instance_id="execution-instance",
        scope_ref="exec-scope", account_ref=gateway.ACCOUNT, transport_ref="exec-transport")]}}
    joint["communication"]["profiles"]["exec-transport"] = profile(exec_endpoint, "exec-security")
    exec_route = dict(mount="broker.execution_parent", service_id="execution", instance_id="execution-instance",
                      scope_ref="exec-scope", scope=copy.deepcopy(scope), identity=copy.deepcopy(identity))
    routing = CONFIG.to_plain()
    routing["component"] = "execution-instance"
    routing["instruments"] = [gateway.INSTRUMENT.to_dict()]
    routing["rules"][0]["match"].update(instrument=gateway.INSTRUMENT.to_dict(), side="buy")
    raw["execution"] = dict(client_config=joint, route=exec_route, peer=dict(role="service",
        principal_ref="execution-principal", actor_ref="execution", delegate_ref=None),
        requested_operations=sorted(EXEC_OPS), routing=routing)
    return raw


def _assert_no_gateway_commands(path):
    with sqlite3.connect(path / "journal.sqlite") as journal:
        for table in ("direct_journal_commands", "direct_delegated_commands"):
            assert journal.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("execution_available,new_logical_run", [(True, False), (False, False), (True, True)],
                         ids=["receipt-reopen", "unavailable", "new-logical-run"])
def test_gateway_execution_parent_client_chain_and_reopen(tmp_path, monkeypatch, execution_available, new_logical_run):
    context = multiprocessing.get_context("spawn")
    messages, controls = context.Queue(), context.Queue()
    keys = {name: zmq.curve_keypair() for name in ("gateway", "strategy", "execution", "risk")}
    endpoint = gateway._free_endpoint()
    process = context.Process(target=gateway._gateway, args=(str(tmp_path), endpoint, keys["gateway"],
        {keys["strategy"][0]: gateway.STRATEGY.principal_ref,
         keys["risk"][0]: gateway.RISK.principal_ref}, messages, controls))
    process.start()
    host_box, requests, queries = [], [], []
    def execution_handler(op, envelope):
        if op == QUERY:
            queries.append(dict(envelope.payload["arguments"]))
            return {"local_only": True, "found": False}
        assert op == SUBMIT
        payload = dict(envelope.payload["arguments"])
        host = host_box[0]
        (key,) = host.iter_order_snapshots()
        route = host.load_execution_route(key)
        assert route.kind == "EXECUTION_PARENT"
        assert host.local_order_notifications()[key]["status"] == "pending"
        assert payload["spec"]["risk_selected"] is True
        digest = hashlib.sha256(encode_wire_value(payload)).hexdigest()
        assert route.request_sha256 == digest and route.request_id == payload["request_id"]
        requests.append(payload)
        return dict(local_only=True, status="RECEIVED", request_id=payload["request_id"],
                    parent_ref=payload["spec"]["parent_ref"], request_sha256=digest)
    def risk_handler(op, _request):
        pytest.fail("Risk order operation on Execution parent: " + op)
    execution = risk = store = None
    try:
        ready = messages.get(timeout=45)
        assert ready[0] == "ready", ready
        execution = SyntheticPeer("execution", keys["execution"], keys["strategy"][0], execution_handler,
                                  available=execution_available)
        risk = SyntheticPeer("risk", keys["risk"], keys["strategy"][0], risk_handler)
        path = tmp_path / "strategy"
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(ready[2], gateway.ACCOUNT, gateway.STRATEGY.actor_ref,
                                        gateway.STRATEGY.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref=gateway.STRATEGY.principal_ref,
            actor_ref=gateway.STRATEGY.actor_ref, execution_domain_ref=gateway.DOMAIN,
            account_scope=gateway.ACCOUNT, strategy_scope=gateway.STRATEGY.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        host_box.append(host)
        raw = _raw(endpoint, execution.endpoint, risk.endpoint, ready[2])
        profiles = {"security": ClientCurveKeys(keys["gateway"][0], *keys["strategy"]),
                    "exec-security": ClientCurveKeys(keys["execution"][0], *keys["strategy"]),
                    "risk-security": ClientCurveKeys(keys["risk"][0], *keys["strategy"])}
        store = BtApiStore(config={"gateway_strategy": raw}, gateway_host=host,
                           gateway_security_profiles=profiles,
                           contract_metadata={"rb": {"quantity_unit": "lots", "time_in_force": "GFD",
                               "instrument_key": gateway.INSTRUMENT.to_dict(), "exchange_name": gateway.ROUTE}})
        store.start()
        api = store.gateway_api
        assert api.risk_selected and api.execution_selected
        assert api.execution_available is execution_available
        assert store._gateway_run_lock.held
        data, broker, strategy = framework()
        broker.store = store
        monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: {
            "key": {"source_ref": "synthetic", "entitlement_ref": "synthetic",
                    "instrument": gateway.INSTRUMENT.to_dict(), "channel": "tick", "depth": None,
                    "timeframe": None}, "epoch": "synthetic", "sequence": 1, "message_id": "synthetic"})
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={}, instrument_by_ref={"rb": gateway.INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(gateway.ROUTE, "UTC"), sequence=state.sequence)
        order = _limit_order(strategy, data)
        broker.submit(order)
        key = order.info["gateway_request_key"]
        if not execution_available:
            assert not requests and order.status == order.Submitted and order.executed.size == 0
            assert order.info["execution_routing_outcome"] == "EXECUTION_UNKNOWN"
            assert host.load_execution_route(key).kind == "PENDING"
            assert host.load_record(key) is None and host.load_delegated_command(key) is None
            assert SUBMIT not in execution.calls and not any(op.startswith("risk.order.") for op in risk.calls)
            _assert_no_gateway_commands(tmp_path)
            broker.cancel(order)
            assert order.status == order.Submitted
            return
        assert len(requests) == 1 and order.status == order.Submitted and order.executed.size == 0
        assert order.info["execution_routing_outcome"] == "EXECUTION_LOCAL_RECEIPT"
        assert host.load_execution_route(key).kind == "EXECUTION_PARENT"
        assert host.load_record(key) is None and host.load_delegated_command(key) is None
        _assert_no_gateway_commands(tmp_path)
        assert execution.calls.count("service.register") == 1 and risk.calls.count("service.register") == 1
        with sqlite3.connect(tmp_path / "registry.sqlite") as registry:
            assert registry.execute("SELECT count(*) FROM sessions WHERE principal=?",
                                    (gateway.STRATEGY.principal_ref,)).fetchone()[0] == 1
        assert not any(op.startswith("risk.order.") for op in risk.calls)
        deliver(broker, strategy)
        broker.cancel(order)
        assert order.status == order.Submitted
        broker.p.stop_cancel_timeout = 0
        assert broker._gateway_stop_working_orders()["unresolved_working_orders"] == 1
        # Strictly close the original runtime before opening the same durable state.
        store.stop()
        assert api.cleanup_confirmed and store._gateway_execution_db is None
        assert not store._gateway_run_lock or not store._gateway_run_lock.held
        assert execution.calls.count("service.unregister") == 1
        assert risk.calls.count("service.unregister") == 1
        with sqlite3.connect(tmp_path / "registry.sqlite") as registry:
            assert registry.execute("SELECT count(*) FROM sessions WHERE principal=?",
                                    (gateway.STRATEGY.principal_ref,)).fetchone()[0] == 0
        store = None
        reopened = GatewayPendingHost(path, state.strategy_uuid, binding)
        host_box[0] = reopened
        original_route = reopened.load_execution_route(key)
        restarted_raw = copy.deepcopy(raw)
        if new_logical_run:
            for selection in (restarted_raw, restarted_raw["risk"], restarted_raw["execution"]):
                selection["route"]["scope"]["run_id"] = "strategy-run-after-restart"
        store = BtApiStore(config={"gateway_strategy": restarted_raw}, gateway_host=reopened,
                           gateway_security_profiles=profiles,
                           contract_metadata={"rb": {"quantity_unit": "lots", "time_in_force": "GFD",
                               "instrument_key": gateway.INSTRUMENT.to_dict(), "exchange_name": gateway.ROUTE}})
        if new_logical_run:
            with pytest.raises(ThreadedRuntimeError, match="REGISTRATION_SCOPE_MISMATCH"):
                store.start()
            assert len(requests) == 1 and reopened.load_execution_route(key) == original_route
            _assert_no_gateway_commands(tmp_path)
            failed_api = store.gateway_api
            store.stop()
            if failed_api is not None:
                assert failed_api.cleanup_confirmed
            assert store._gateway_execution_db is None
            assert not store._gateway_run_lock or not store._gateway_run_lock.held
            with sqlite3.connect(tmp_path / "registry.sqlite") as registry:
                assert registry.execute("SELECT count(*) FROM sessions WHERE principal=?",
                                        (gateway.STRATEGY.principal_ref,)).fetchone()[0] == 0
            store = None
            return
        store.start()
        new_api = store.gateway_api
        result = new_api.execution_order_status(gateway.ROUTE, reopened.load_intent(key))
        assert result.routed and result.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
        assert result.code == "EXECUTION_UNVERIFIED_REPLY"
        assert (result.request_id, result.request_sha256) == (original_route.request_id,
                                                              original_route.request_sha256)
        assert queries == [{"request_id": original_route.request_id}] and len(requests) == 1
        assert reopened.load_execution_route(key) == original_route
        assert original_route.parent_ref == requests[0]["spec"]["parent_ref"]
        assert reopened.load_record(key) is None and reopened.load_delegated_command(key) is None
        assert not any(op.startswith("risk.order.") for op in risk.calls)
        data2, broker2, strategy2 = framework()
        broker2.store = store
        broker2.bind_gateway_execution_stream(strategy2, api=new_api, host=reopened,
            data_by_ref={"rb": data2}, orders_by_key={}, instrument_by_ref={"rb": gateway.INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(gateway.ROUTE, "UTC"), sequence=state.sequence)
        recovered = broker2._gateway_binding(strategy2, required=True).orders[key]
        broker2.cancel(recovered)
        broker2.next()
        assert broker2.gateway_execution_stream_status() == "EXECUTION_RECOVERY_PENDING"
        assert recovered.status == recovered.Submitted and recovered.executed.size == 0
        assert len(requests) == 1 and reopened.load_record(key) is None
        _assert_no_gateway_commands(tmp_path)
    finally:
        try:
            if store is not None:
                final_api = store.gateway_api
                store.stop()
                if final_api is not None:
                    assert final_api.cleanup_confirmed
        finally:
            try:
                if execution is not None:
                    execution.close()
            finally:
                try:
                    if risk is not None:
                        risk.close()
                finally:
                    controls.put("stop")
                    process.join(30)
                    assert not process.is_alive(), "local Gateway failed to stop"
                    assert process.exitcode == 0
