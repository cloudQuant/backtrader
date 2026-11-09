"""Spawned synthetic Gateway -> actual BT stream consumer and notification replay.

No native provider or account connection.  Local receipts and fills are
synthetic; the test is not a production Broker configuration or venue claim.
"""

import multiprocessing
import os
import queue
import socket
import time
import traceback
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import backtrader as bt
import pytest
import zmq
from bt_api_base.direct_write_protocol import (
    DirectExecutionEventKind,
    NativeOrderIdentity,
    PreDispatchRecord,
    WriteOperation,
)
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_protocol import GatewayReturnFact
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.bt_api import BtApi
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_stream_service import (
    GatewayExecutionStreamService,
    STREAM_OPERATIONS,
)
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys

from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework

ACCOUNT, DOMAIN, ROUTE = "account-a", "paper:demo", "TEST"
SERVICE = WireIdentity(WireRole.SERVICE, "gateway-principal", "gateway-service")
CLIENT = WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a")
INSTRUMENT = MarketInstrumentKey("synthetic", "venue", "paper", "future", "rb", "rb")
OPS = (
    frozenset({"direct.reserve", "direct.release", "direct.command_status", "direct.dispatch"})
    | STREAM_OPERATIONS
)


def _service_config(endpoint):
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": SERVICE.actor_ref,
            "scope_ref": "scope-a",
            "transport_ref": "transport",
            "registration_policy_ref": "policy",
            "service_requirements_ref": "requirements",
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
                    "transport": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": "security",
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
                                "transport_ref": "transport",
                            }
                        ]
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "transport": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": "security",
                    }
                },
            },
        }
    )


def _identity():
    return NativeOrderIdentity(
        ROUTE, "order-a-order-a", {"inst_id": "rb", "trading_day": "20300101"}, 1
    )


def _fact(trade, *, dated, wrong=False):
    key = "TEST:" + _identity().client_order_id
    return GatewayReturnFact(
        ACCOUNT,
        ROUTE,
        replace(INSTRUMENT, venue="other") if wrong else INSTRUMENT,
        "20300101",
        DirectExecutionEventKind.TRADE,
        "synthetic-" + trade,
        identity=_identity(),
        identity_keys=(key,),
        binding_keys=(key,),
        venue_key=key,
        trade_key=("venue", trade),
        side="buy",
        offset="open",
        order_quantity="2",
        trade_quantity="1",
        trade_price="10",
        trade_time="09:00:00",
        schema_version=4 if dated else 1,
        trade_date="20300101" if dated else None,
    )


def _gateway(root, endpoint, server_keys, client_keys, messages, controls):
    host = owner = stream = None
    try:
        root = Path(root)
        (root / "guard").mkdir()
        resources = []

        def owner_factory():
            guard = LocalAccountSessionGuard(root / "guard", ACCOUNT, "synthetic-owner")
            journal = GatewayDirectCommandJournal.create(
                root / "journal.sqlite", ACCOUNT, generation=guard.acquire()
            )
            ledger = GatewayDirectExecutionLedger(journal, guard)

            def native(payload, port, scope):
                identity = _identity()
                record = PreDispatchRecord(
                    operation=WriteOperation.PLACE,
                    host_scope=scope,
                    exchange_name=ROUTE,
                    symbol=payload["symbol"],
                    identity=identity,
                    target_identity=None,
                    request_summary=payload,
                    trading_day="20300101",
                    session_generation=1,
                    created_at_utc="synthetic",
                )
                marker = port.commit(record)
                return NativeDispatchOutcome(marker is not None, identity, marker)

            dispatcher = GatewayDirectDispatcher(
                journal,
                ROUTE,
                guard,
                native,
                lambda identity: ("TEST:" + identity.client_order_id,),
                lambda row: True,
            )
            resources.append((journal, ledger))
            return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

        owner = GatewayDirectOwner(
            owner_factory, queue_size=4, max_queue_wait_seconds=20, busy_timeout_seconds=20
        )
        assert owner.start(10)
        journal, ledger = resources[0]
        stream = GatewayExecutionStreamService(
            ledger, journal, {CLIENT.principal_ref: CLIENT.actor_ref}, execution_domain_ref=DOMAIN
        )
        binding = GatewayDirectServiceBinding(
            journal,
            {CLIENT.principal_ref: GatewayDirectGrant(CLIENT.actor_ref, frozenset({"rb"}))},
            owner=owner,
            execution_stream=stream,
            execution_domain_ref=DOMAIN,
        )
        grant = PrincipalGrant(
            CLIENT,
            (
                ResourceGrant(
                    "gateway-a",
                    "service.direct_write",
                    "scope-a",
                    WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT.actor_ref),
                    OPS,
                ),
            ),
        )
        authority = TrustedServiceAuthority(
            identity=SERVICE,
            scope=WireScope(DOMAIN),
            scope_ref="scope-a",
            scope_version="scope-v1",
            security_ref="security",
            security_version="security-v1",
            registration_policy_ref="policy",
            registration_policy_version="policy-v1",
            service_requirements_ref="requirements",
            service_requirements_version="requirements-v1",
            curve_public_key=server_keys[0],
            curve_secret_key=server_keys[1],
            principals={client_keys[0]: CLIENT.principal_ref},
            grants={CLIENT.principal_ref: (grant,)},
        )
        host = ServiceHost(
            _service_config(endpoint),
            authority,
            root / "registry.sqlite",
            lambda *_: ComponentResources.borrowed({"binding": binding}, ready=lambda: True),
        )
        host.start()
        messages.put(("ready", os.getpid(), journal.journal_id))
        while True:
            try:
                command = controls.get_nowait()
            except queue.Empty:
                command = None
            if command == "stop":
                break
            if command in {"partial", "date", "final", "wrong"}:
                fact = _fact(
                    "one" if command != "final" else "two",
                    dated=command in {"date", "final", "wrong"},
                    wrong=command == "wrong",
                )
                result = owner.submit_service_call(lambda fact=fact: ledger.ingest(fact)).result(
                    timeout_seconds=10
                )
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


def _session(endpoint, server_public, client_keys, binding, host):
    route = GatewayClientRoute(
        "broker.direct_write",
        SERVICE.actor_ref,
        "gateway-a",
        "scope-a",
        WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=CLIENT.actor_ref, run_id="run-a"),
        CLIENT,
    )
    session = GatewayStrategyClientSession(
        _client_config(endpoint),
        binding=binding,
        route=route,
        peer=SERVICE,
        security_profiles={"security": ClientCurveKeys(server_public, *client_keys)},
        host=host,
        requested_operations=OPS,
    )
    return session, BtApi.from_gateway(session, exchange_name=ROUTE, owns_session=True)


def _progress(api):
    result = api.gateway_execution_stream(ROUTE).progress(timeout_seconds=5)
    assert result.outcome == "OBSERVED"
    return result.progress.acknowledged_sequence


def _wait_sent(api):
    deadline = time.monotonic() + 8
    while True:
        result = api.command_status(ROUTE, "order-a", timeout_seconds=5)
        if result.record is not None and result.record.state == "SENT":
            return
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _deliver(broker, strategy):
    notice = broker.get_notification()
    assert notice is not None
    strategy._addnotification(notice)
    strategy._notify()
    strategy.clear()


def _client(root, endpoint, server_public, keys, journal_id, phase, messages, controls):
    api = None
    try:
        path = Path(root) / "strategy"
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        if phase in {"first", "wrong"}:
            path.mkdir()
            state = StrategyStateDir.initialize(path)
            GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
            GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
            consumer = gateway_execution_consumer_ref(
                principal_ref=CLIENT.principal_ref,
                actor_ref=CLIENT.actor_ref,
                execution_domain_ref=DOMAIN,
                account_scope=ACCOUNT,
                strategy_scope=CLIENT.actor_ref,
            )
            host = GatewayPendingHost.upgrade_for_execution(
                path, state.strategy_uuid, binding, consumer_ref=consumer
            )
            (Path(root) / "uuid.txt").write_text(state.strategy_uuid, encoding="ascii")
        else:
            uuid = (Path(root) / "uuid.txt").read_text(encoding="ascii")
            host = GatewayPendingHost(path, uuid, binding)
        session, api = _session(endpoint, server_public, keys, binding, host)
        api.start(timeout_seconds=10)
        data, broker, strategy = framework()
        if phase in {"first", "wrong"}:
            order = bt.BuyOrder(
                owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit
            )
            order.addcomminfo(broker.getcommissioninfo(data))
            order.submit(broker)
            order.accept(broker)
            request = OrderRequest(
                symbol="rb",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("2"),
                account_id=ACCOUNT,
                client_order_id="order-a",
                price=Decimal("10"),
                idempotency_key="order-a",
                offset="open",
            )
            assert api.reserve_order(ROUTE, request).outcome == "OBSERVED"
            host.save_intent(host.load_intent("order-a"), bt_ref=order.ref)
            assert api.dispatch_order(ROUTE, "order-a").outcome == "QUEUED"
            _wait_sent(api)
            orders = {"order-a": order}
        else:
            orders = {}
        broker.bind_gateway_execution_stream(
            strategy,
            api=api,
            host=host,
            data_by_ref={"rb": data},
            orders_by_key=orders,
            instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(ROUTE, "UTC"),
            timeout_seconds=5,
        )
        messages.put(("bound", phase, os.getpid()))
        assert controls.get(timeout=20) == "continue"
        if phase == "wrong":
            try:
                broker.next()
            except RuntimeError as exc:
                assert "EVENT_BINDING" in str(exc)
            else:
                raise AssertionError("mismatched full instrument accepted")
            assert order.executed.size == 0 and _progress(api) == 0
            messages.put(("wrong_rejected",))
        elif phase == "first":
            broker.next()
            assert order.executed.size == 1 and broker.positions["rb"].size == 1
            assert order.status == order.Partial and not strategy.events
            assert _progress(api) == 0
            strategy.fail = "order"
            strategy._addnotification(broker.get_notification())
            try:
                strategy._notify()
            except RuntimeError as exc:
                assert "callback" in str(exc)
            else:
                raise AssertionError("callback did not fail")
            batch = host.load_execution_notification_batch()
            assert batch["status"] == "pending"
            assert _progress(api) == 0
            messages.put(
                ("failed", strategy.events[0][1], batch["notifications"], order.executed.size)
            )
        else:
            order = next(iter(broker.orders.values()))
            trade = next(iter(next(iter(strategy._trades.values())).values()))[0]
            assert order.executed.size == broker.positions["rb"].size == trade.size == 1
            assert _progress(api) == 0
            batch = host.load_execution_notification_batch()
            assert batch["status"] == "pending"
            strategy._notify()
            assert host.load_execution_notification_batch()["status"] == "confirmed"
            assert _progress(api) == 0
            assert order.executed.size == broker.positions["rb"].size == trade.size == 1
            messages.put(("replayed", strategy.events, batch["notifications"]))
            replayed_events = list(strategy.events)
            strategy.clear()
            broker.next()
            assert _progress(api) == 1
            # The second stored event enriches the same fill's trade date.
            assert order.executed.size == broker.positions["rb"].size == trade.size == 1
            assert strategy.events == replayed_events
            assert set(order.info["gateway_trade_dates"].values()) == {"20300101"}
            broker.next()
            assert _progress(api) == 2
            messages.put(("metadata", order.executed.size, trade.size))
            assert controls.get(timeout=20) == "final"
            broker.next()
            assert order.executed.size == 2 and broker.positions["rb"].size == 2
            assert order.status == order.Completed and _progress(api) == 2
            _deliver(broker, strategy)
            assert _progress(api) == 2
            final_events = strategy.events[len(replayed_events) :]
            assert [item[0] for item in final_events] == ["order"], final_events
            assert final_events[0][3] == 2 and trade.size == 2
            broker.next()
            assert _progress(api) == 3
            messages.put(
                ("final", order.executed.size, broker.positions["rb"].size, strategy.events)
            )
    except BaseException:
        messages.put(("error", phase, traceback.format_exc()))
    finally:
        if api is not None:
            try:
                api.close(timeout_seconds=10)
            except BaseException:
                messages.put(("cleanup_error", phase, traceback.format_exc()))


def _message(q, expected):
    value = q.get(timeout=30)
    assert value[0] == expected, value
    return value


def _join(process):
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("synthetic process required termination")
    assert process.exitcode == 0


@pytest.mark.parametrize("mismatch", [False, True])
def test_spawned_gateway_real_bt_notifications_and_recovery(tmp_path, mismatch):
    ctx = multiprocessing.get_context("spawn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        endpoint = "tcp://127.0.0.1:" + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gateway_messages, gateway_controls = ctx.Queue(), ctx.Queue()
    client_messages, client_controls = ctx.Queue(), ctx.Queue()
    server = ctx.Process(
        target=_gateway,
        args=(
            str(tmp_path),
            endpoint,
            server_keys,
            client_keys,
            gateway_messages,
            gateway_controls,
        ),
    )
    clients = []
    server.start()
    try:
        ready = _message(gateway_messages, "ready")
        assert ready[1] == server.pid != os.getpid()
        phase = "wrong" if mismatch else "first"

        def start_client(phase):
            process = ctx.Process(
                target=_client,
                args=(
                    str(tmp_path),
                    endpoint,
                    server_keys[0],
                    client_keys,
                    ready[2],
                    phase,
                    client_messages,
                    client_controls,
                ),
            )
            process.start()
            clients.append(process)
            bound = _message(client_messages, "bound")
            assert bound[1:] == (phase, process.pid) and process.pid != os.getpid()
            return process

        first = start_client(phase)
        for command in ("wrong",) if mismatch else ("partial", "date"):
            gateway_controls.put(command)
            result = _message(gateway_messages, "ingested")
            assert result[1:] == (command, "ATTRIBUTED")
        client_controls.put("continue")
        if mismatch:
            _message(client_messages, "wrong_rejected")
            _join(first)
        else:
            failed = _message(client_messages, "failed")
            assert failed[3] == 1 and failed[1] == failed[2][0]["notification_id"]
            _join(first)
            resumed = start_client("resumed")
            assert resumed.pid != first.pid
            client_controls.put("continue")
            replay = _message(client_messages, "replayed")
            assert replay[1][0][:3] == ("order", failed[1], True)
            assert replay[2] == failed[2]
            assert [item[0] for item in replay[1]] == ["order", "trade"]
            assert _message(client_messages, "metadata")[1:] == (1, 1)
            gateway_controls.put("final")
            assert _message(gateway_messages, "ingested")[1:] == ("final", "ATTRIBUTED")
            client_controls.put("final")
            assert _message(client_messages, "final")[1:3] == (2, 2)
            _join(resumed)
    finally:
        for process in clients:
            if process.is_alive():
                process.terminate()
                process.join(5)
        gateway_controls.put("stop")
        _join(server)
        assert _message(gateway_messages, "closed") == ("closed", server.pid)
        for q in (gateway_messages, gateway_controls, client_messages, client_controls):
            q.close()
