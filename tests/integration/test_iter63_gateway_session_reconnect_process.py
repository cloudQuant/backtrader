"""D63-03: a BT strategy outlives a Gateway restart and registers again.

A real spawned Gateway (real ServiceHost, CURVE, SQLite journal and Registry;
synthetic native boundary) is stopped and started again on the same journal
while one BT process with a real configured ``BtApiStore`` keeps stepping its
broker. No account, venue or external network.
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import socket
import time
import traceback
from pathlib import Path

import backtrader as bt
import pytest
import zmq
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.service_protocol import WireScope
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_direct_client import build_gateway_order_intent
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_stream_service import GatewayExecutionStreamService
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys

from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.integration.test_iter63_gateway_stream_consumer_process import (
    ACCOUNT,
    CLIENT,
    DOMAIN,
    INSTRUMENT,
    OPS,
    ROUTE,
    SERVICE,
    _configured_raw,
    _deliver,
    _fact,
    _historical_request,
    _join,
    _message,
    _seed_synthetic_historical_sent,
    _service_config,
)
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework


def _restartable_gateway(root, endpoint, server_keys, client_keys, messages, controls):
    """One Gateway run over a journal that an earlier run may have created."""
    host = owner = stream = None
    try:
        root = Path(root)
        (root / "guard").mkdir(exist_ok=True)
        identity = root / "journal-id.txt"
        resources = []

        def owner_factory():
            guard = LocalAccountSessionGuard(root / "guard", ACCOUNT, "synthetic-owner")
            generation = guard.acquire()
            if identity.exists():
                journal = GatewayDirectCommandJournal(
                    root / "journal.sqlite", ACCOUNT, generation=generation,
                    expected_journal_id=identity.read_text(encoding="ascii"), minimum_revision=0)
            else:
                journal = GatewayDirectCommandJournal.create(
                    root / "journal.sqlite", ACCOUNT, generation=generation)
                _seed_synthetic_historical_sent(journal)
                identity.write_text(journal.journal_id, encoding="ascii")
            ledger = GatewayDirectExecutionLedger(journal, guard)

            def native(payload, port, scope):
                raise AssertionError("this scenario never dispatches")

            dispatcher = GatewayDirectDispatcher(
                journal, ROUTE, guard, native,
                lambda native_identity: ("TEST:" + native_identity.client_order_id,),
                lambda row: True)
            resources.append((journal, ledger))
            return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

        owner = GatewayDirectOwner(owner_factory, queue_size=4, max_queue_wait_seconds=20,
                                   busy_timeout_seconds=20)
        assert owner.start(10)
        journal, ledger = resources[0]
        stream = GatewayExecutionStreamService(
            ledger, journal, {CLIENT.principal_ref: CLIENT.actor_ref}, execution_domain_ref=DOMAIN)
        binding = GatewayDirectServiceBinding(
            journal, {CLIENT.principal_ref: GatewayDirectGrant(CLIENT.actor_ref, frozenset({"rb"}))},
            owner=owner, execution_stream=stream, execution_domain_ref=DOMAIN)
        grant = PrincipalGrant(CLIENT, (ResourceGrant(
            "gateway-a", "service.direct_write", "scope-a",
            WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT.actor_ref), OPS),))
        authority = TrustedServiceAuthority(
            identity=SERVICE, scope=WireScope(DOMAIN), scope_ref="scope-a", scope_version="scope-v1",
            security_ref="security", security_version="security-v1", registration_policy_ref="policy",
            registration_policy_version="policy-v1", service_requirements_ref="requirements",
            service_requirements_version="requirements-v1", curve_public_key=server_keys[0],
            curve_secret_key=server_keys[1], principals={client_keys[0]: CLIENT.principal_ref},
            grants={CLIENT.principal_ref: (grant,)})
        host = ServiceHost(
            _service_config(endpoint), authority, root / "registry.sqlite",
            lambda *_: ComponentResources.borrowed({"binding": binding}, ready=lambda: True))
        host.start()
        messages.put(("ready", os.getpid(), journal.journal_id, journal.generation))
        while True:
            try:
                command = controls.get_nowait()
            except queue.Empty:
                command = None
            if command == "stop":
                break
            if command in {"date", "final"}:
                fact = _fact("one" if command == "date" else "two", dated=True)
                result = owner.submit_service_call(lambda fact=fact: ledger.ingest(fact)).result(
                    timeout_seconds=10)
                messages.put(("ingested", command, result.disposition))
            host.serve_once(10)
    except BaseException:
        messages.put(("error", traceback.format_exc()))
    finally:
        try:
            if host is not None and host.state == "started":
                host.close()
            if stream is not None:
                assert stream.close()
            if owner is not None:
                assert owner.close(10)
            messages.put(("closed", os.getpid()))
        except BaseException:
            messages.put(("cleanup_error", traceback.format_exc()))


def _step_until(broker, predicate, seconds, *, pause=0.05):
    """Step the broker like a live Cerebro loop; any exception fails the test."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        broker.next()
        if predicate():
            return True
        time.sleep(pause)
    return False


def _strategy_process(root, endpoint, server_public, keys, journal_id, messages, controls):
    store = None
    try:
        from backtrader.stores.btapistore import BtApiStore

        path = Path(root) / "strategy"
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(
            principal_ref=CLIENT.principal_ref, actor_ref=CLIENT.actor_ref, execution_domain_ref=DOMAIN,
            account_scope=ACCOUNT, strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(
            path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        store = BtApiStore(
            config={"gateway_strategy": _configured_raw(endpoint, journal_id),
                    "contracts": {"rb": {"quantity_unit": "lots", "time_in_force": "GFD"}}},
            gateway_host=host,
            gateway_security_profiles={"security": ClientCurveKeys(server_public, *keys)})
        data, broker, strategy = framework()
        broker.store = store
        broker.start()
        first_api = store.gateway_api
        # An order this strategy sent earlier (pre-seeded SENT at the Gateway).
        order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
        order.addcomminfo(broker.getcommissioninfo(data))
        order.submit(broker)
        order.accept(broker)
        route = store.gateway_strategy_config.route
        host.save_intent(build_gateway_order_intent(binding, route, _historical_request()),
                         bt_ref=order.ref)
        observed = first_api.command_status(ROUTE, "order-a")
        assert observed.outcome == "OBSERVED" and observed.record.state == "SENT"
        from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy

        broker.bind_gateway_execution_stream(
            strategy, api=first_api, host=host, data_by_ref={"rb": data},
            orders_by_key={"order-a": order}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(ROUTE, "UTC"), timeout_seconds=5)
        stream_binding = broker._gateway_stream_binding
        messages.put(("bound", os.getpid()))

        assert controls.get(timeout=30) == "first-fill"
        assert _step_until(broker, lambda: order.executed.size == 1, 20)
        _deliver(broker, strategy)
        assert _step_until(
            broker, lambda: host.load_execution_checkpoint().acknowledged_sequence >= 1, 20)
        acknowledged = host.load_execution_checkpoint().acknowledged_sequence
        messages.put(("first-fill", order.executed.size, acknowledged))

        assert controls.get(timeout=30) == "outage"
        # The Gateway is gone. The strategy keeps stepping and reports it; it
        # neither raises nor delivers anything, and a submit would be refused.
        states = set()

        def waiting():
            states.add(broker.gateway_execution_stream_status())
            return "GATEWAY_UNAVAILABLE" in states

        assert _step_until(broker, waiting, 100)
        with pytest.raises(RuntimeError, match="GATEWAY_STREAM_GATEWAY_UNAVAILABLE"):
            broker._gateway_stream_check(stream_binding)
        assert order.executed.size == 1 and broker.get_notification() is None
        assert store.gateway_session_generation == 0
        messages.put(("waiting", sorted(states), store.gateway_session_state()))

        assert controls.get(timeout=30) == "gateway-back"
        # Same process, same Store, same order objects: a new registration.
        assert _step_until(
            broker, lambda: store.gateway_session_generation == 1
            and broker.gateway_execution_stream_status() == "ACTIVE", 60, pause=0.2), (
            store.gateway_session_generation, store.gateway_session_state(),
            store._gateway_reconnect_reason, stream_binding.state)
        assert store.gateway_api is not first_api and store.is_connected
        assert stream_binding.api is store.gateway_api and stream_binding.strategy is strategy
        assert first_api.lifecycle_state != "open"  # fenced; its runtime ended as failed
        assert broker._gateway_binding(strategy, required=True).orders["order-a"] is order
        # Nothing was replayed or lost across the restart.
        checkpoint = host.load_execution_checkpoint()
        assert checkpoint.acknowledged_sequence == acknowledged and order.executed.size == 1
        again = store.gateway_api.command_status(ROUTE, "order-a")
        assert again.outcome == "OBSERVED" and again.record.state == "SENT"
        assert again.record.reservation_id == observed.record.reservation_id
        messages.put(("reconnected", os.getpid(), store.gateway_session_generation))

        assert controls.get(timeout=30) == "second-fill"
        assert _step_until(broker, lambda: order.executed.size == 2, 20)
        assert order.status == order.Completed and broker.positions["rb"].size == 2
        _deliver(broker, strategy)
        assert _step_until(
            broker, lambda: host.load_execution_checkpoint().acknowledged_sequence > acknowledged, 20)
        messages.put(("second-fill", order.executed.size, broker.positions["rb"].size,
                      [item[0] for item in strategy.events]))
    except BaseException:
        messages.put(("error", traceback.format_exc()))
    finally:
        if store is not None and store.gateway_api is not None:
            try:
                store.stop(timeout=10)
            except BaseException:
                messages.put(("error", traceback.format_exc()))


def test_strategy_keeps_running_and_registers_again_after_gateway_restart(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        endpoint = "tcp://127.0.0.1:" + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    queues = [ctx.Queue() for _ in range(6)]
    gm1, gc1, gm2, gc2, cm, cc = queues
    arguments = (str(tmp_path), endpoint, server_keys, client_keys)
    first = ctx.Process(target=_restartable_gateway, args=(*arguments, gm1, gc1))
    second = ctx.Process(target=_restartable_gateway, args=(*arguments, gm2, gc2))
    client = None
    first.start()
    try:
        ready = _message(gm1, "ready")
        client = ctx.Process(target=_strategy_process, args=(
            str(tmp_path), endpoint, server_keys[0], client_keys, ready[2], cm, cc))
        client.start()
        assert _message(cm, "bound")[1] == client.pid
        gc1.put("date")
        assert _message(gm1, "ingested")[1:] == ("date", "ATTRIBUTED")
        cc.put("first-fill")
        assert _message(cm, "first-fill")[1] == 1

        # Normal Gateway stop: its owner, guard and journal are closed cleanly.
        gc1.put("stop")
        _join(first)
        assert _message(gm1, "closed") == ("closed", first.pid)
        cc.put("outage")
        # Within its lease the SDK session first only fails reads; once the
        # lease has run out the session is lost and the strategy waits.
        waiting = cm.get(timeout=120)
        assert waiting[0] == "waiting", waiting
        assert "GATEWAY_UNAVAILABLE" in waiting[1] and client.is_alive()

        second.start()
        restarted = _message(gm2, "ready")
        # The same journal under a new owner generation (a new Gateway run).
        assert restarted[2] == ready[2] and restarted[3] != ready[3]
        cc.put("gateway-back")
        deadline = time.monotonic() + 150
        while True:
            try:
                reconnected = cm.get(timeout=1)
                break
            except queue.Empty:
                assert time.monotonic() < deadline and client.is_alive()
        assert reconnected == ("reconnected", client.pid, 1), reconnected

        gc2.put("final")
        assert _message(gm2, "ingested")[1:] == ("final", "ATTRIBUTED")
        cc.put("second-fill")
        assert _message(cm, "second-fill")[1:3] == (2, 2)
        _join(client)
    finally:
        if client is not None and client.is_alive():
            client.terminate()
            client.join(5)
        for process, controls in ((first, gc1), (second, gc2)):
            if process.is_alive():
                controls.put("stop")
                process.join(20)
            if process.is_alive():
                process.terminate()
                process.join(5)
        for item in queues:
            item.close()
