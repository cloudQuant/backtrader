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
import uuid
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
from bt_api_py.gateway_direct_client import GatewayClientRoute, build_gateway_order_intent
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


def _historical_request():
    return OrderRequest(symbol="rb", side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=Decimal("2"), account_id=ACCOUNT, client_order_id="order-a", price=Decimal("10"),
        idempotency_key="order-a", offset="open")


def _seed_synthetic_historical_sent(journal):
    """Install a clearly synthetic prior SENT fact; never dispatch or call native."""
    from bt_api_base.gateway_direct_protocol import canonical_gateway_payload
    from bt_api_gateway.direct_command_journal import payload_digest

    payload = _historical_request().to_dict()
    native = _identity()
    identity = {"exchange_name": native.exchange_name, "client_order_id": native.client_order_id,
        "session_generation": native.session_generation,
        "fields_json": canonical_gateway_payload(dict(native.fields))}
    key = "TEST:" + native.client_order_id
    reservation = 'historical-' + str(uuid.uuid4())
    with journal._transaction() as db:
        db.execute("INSERT INTO direct_journal_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ACCOUNT, CLIENT.actor_ref, 'order-a', reservation, CLIENT.principal_ref,
             payload_digest(payload), canonical_gateway_payload(payload), journal.generation,
             time.monotonic() + 10, 'SENT', 3, canonical_gateway_payload(identity),
             canonical_gateway_payload([key])))
        db.execute("INSERT INTO direct_journal_strong_keys VALUES (?,?,?)", (ACCOUNT, key, reservation))
        journal._bump(db)
    stored = journal.get(CLIENT.actor_ref, 'order-a', CLIENT.principal_ref)
    assert stored.status == 'SENT' and stored.strong_identity_keys == (key,)


def _gateway(root, endpoint, server_keys, client_keys, messages, controls, seed_history=False):
    host = owner = stream = None
    try:
        root = Path(root)
        (root / "guard").mkdir()
        resources = []
        native_calls = []

        def owner_factory():
            guard = LocalAccountSessionGuard(root / "guard", ACCOUNT, "synthetic-owner")
            journal = GatewayDirectCommandJournal.create(
                root / "journal.sqlite", ACCOUNT, generation=guard.acquire()
            )
            if seed_history:
                _seed_synthetic_historical_sent(journal)
            ledger = GatewayDirectExecutionLedger(journal, guard)

            def native(payload, port, scope):
                native_calls.append(True)
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
            resources.append((journal, ledger, dispatcher))
            return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

        owner = GatewayDirectOwner(
            owner_factory, queue_size=4, max_queue_wait_seconds=20, busy_timeout_seconds=20
        )
        assert owner.start(10)
        journal, ledger, dispatcher = resources[0]
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
            if command == 'native-count':
                messages.put(('native-count', len(native_calls)))
            if command == 'claim-check':
                from bt_api_gateway.direct_dispatch import DirectDispatchError
                def check_reserved():
                    request = _historical_request().to_dict()
                    request['idempotency_key'] = 'fresh-reserved'
                    request['client_order_id'] = 'fresh-reserved'
                    row = journal.reserve(CLIENT.actor_ref, 'fresh-reserved', CLIENT.principal_ref, request)
                    try:
                        dispatcher.dispatch(CLIENT.actor_ref, row.request_key, CLIENT.principal_ref,
                            row.reservation_id, row.digest, row.version)
                    except DirectDispatchError as exc:
                        assert exc.code == 'DISPATCH_CLAIM_UNAVAILABLE'
                    else:
                        raise AssertionError('fresh RESERVED unexpectedly dispatched')
                    after = journal.get(CLIENT.actor_ref, 'fresh-reserved', CLIENT.principal_ref)
                    assert after.status == 'RESERVED' and after.native_identity_json is None
                    assert after.strong_identity_keys == () and not native_calls
                owner.submit_service_call(check_reserved).result(timeout_seconds=10)
                messages.put(('claim-unavailable', len(native_calls)))
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


def _deliver(broker, strategy):
    notice = broker.get_notification()
    assert notice is not None
    strategy._addnotification(notice)
    strategy._notify()
    strategy.clear()


def _client(root, endpoint, server_public, keys, journal_id, phase, messages, controls):
    # This client asserts what each single broker step does. A step that found
    # nothing to do pauses the following ones (_IDLE_READ_INTERVAL_SECONDS); the
    # spawned process therefore steps without that pause.
    import backtrader.brokers._btapi_gateway_stream as _stream_module

    _stream_module._IDLE_READ_INTERVAL_SECONDS = 0.0
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
            request = _historical_request()
            host.save_intent(build_gateway_order_intent(binding, session.route, request), bt_ref=order.ref)
            # Read a pre-seeded historical record; this fixture does not place an order.
            result = api.command_status(ROUTE, "order-a")
            assert result.outcome == "OBSERVED" and result.record.state == "SENT"
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
            True,  # Install only the synthetic historical SENT record.
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
        gateway_controls.put('native-count')
        assert _message(gateway_messages, 'native-count')[1] == 0
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


def test_spawned_gateway_new_reserved_has_no_dispatch_claim_or_native_call(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        endpoint = 'tcp://127.0.0.1:' + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    messages, controls = ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_gateway,
        args=(str(tmp_path), endpoint, server_keys, client_keys, messages, controls))
    server.start()
    try:
        _message(messages, 'ready')
        controls.put('claim-check')
        assert _message(messages, 'claim-unavailable') == ('claim-unavailable', 0)
    finally:
        controls.put('stop')
        _join(server)
        assert _message(messages, 'closed') == ('closed', server.pid)
        messages.close()
        controls.close()


def _submitted_client(root, endpoint, server_public, keys, journal_id, messages, controls):
    api = None
    try:
        path = Path(root) / 'submitted-strategy'
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref=CLIENT.principal_ref,
            actor_ref=CLIENT.actor_ref, execution_domain_ref=DOMAIN, account_scope=ACCOUNT,
            strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        _, api = _session(endpoint, server_public, keys, binding, host)
        api.start(timeout_seconds=10)
        data, broker, strategy = framework()
        from types import SimpleNamespace
        broker.store = SimpleNamespace(contract_metadata={'rb': {'instrument_key': INSTRUMENT.to_dict(),
            'exchange_name': ROUTE, 'quantity_unit': 'lots', 'time_in_force': 'GFD'}})
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
            orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(ROUTE, 'UTC'), timeout_seconds=5,
            sequence=state.sequence)
        order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
        order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
        reserve_calls, reserve = [], api.reserve_order
        def tracked_reserve(*args, **kwargs):
            reserve_calls.append(True)
            return reserve(*args, **kwargs)
        api.reserve_order = tracked_reserve
        before_seq, before_pending = state.sequence.local_seq, host._store._load()
        with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
            broker.submit(order)
        assert state.sequence.local_seq == before_seq and host._store._load() == before_pending
        assert order.status == order.Created and broker.get_notification() is None and not reserve_calls
        messages.put(('unqualified-rejected', os.getpid()))
    except BaseException:
        messages.put(('error', traceback.format_exc()))
    finally:
        if api is not None:
            try:
                api.close(timeout_seconds=5)
            except BaseException:
                messages.put(('error', traceback.format_exc()))


def test_spawned_gateway_strategy_rejects_unqualified_feed_before_intent(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        endpoint = 'tcp://127.0.0.1:' + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gm, gc, cm, cc = ctx.Queue(), ctx.Queue(), ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_gateway, args=(str(tmp_path), endpoint, server_keys, client_keys, gm, gc))
    client = None
    server.start()
    try:
        ready = _message(gm, 'ready')
        client = ctx.Process(target=_submitted_client,
            args=(str(tmp_path), endpoint, server_keys[0], client_keys, ready[2], cm, cc))
        client.start()
        rejected = _message(cm, 'unqualified-rejected')
        assert rejected[1] == client.pid and rejected[1] != server.pid
        _join(client)
    finally:
        if client is not None and client.is_alive():
            client.terminate()
            client.join(5)
        gc.put('stop')
        _join(server)
        assert _message(gm, 'closed') == ('closed', server.pid)
        for q in (gm, gc, cm, cc):
            q.close()


def _configured_raw(endpoint, journal_id):
    raw = {'schema_version': 1, 'exchange_name': ROUTE,
        'client_config': {'client_config_schema_version': 1, 'process_role': 'strategy_client',
            'registration': {'strategy_ref': CLIENT.actor_ref},
            'clients': {'gateway': {'config_schema_version': 1, 'settings': {'bindings': [{
                'mount': 'broker.direct_write', 'service_id': SERVICE.actor_ref,
                'instance_id': 'gateway-a', 'scope_ref': 'scope-a', 'account_ref': ACCOUNT,
                'transport_ref': 'transport'}]}}},
            'communication': {'config_schema_version': 1, 'profiles': {'transport': {
                'backend': 'zmq', 'config_schema_version': 1,
                'endpoints': {'rpc_connect': endpoint}, 'security_profile_ref': 'security'}}}},
        'binding': {'journal_id': journal_id, 'account_scope': ACCOUNT,
                    'strategy_scope': CLIENT.actor_ref, 'principal': CLIENT.principal_ref},
        'route': {'mount': 'broker.direct_write', 'service_id': SERVICE.actor_ref,
            'instance_id': 'gateway-a', 'scope_ref': 'scope-a',
            'scope': {'execution_domain_ref': DOMAIN, 'account_ref': ACCOUNT, 'account_refs': [],
                'strategy_ref': CLIENT.actor_ref, 'run_id': 'run-a', 'manual_book_ref': None,
                'portfolio_ref': None, 'group_id': None, 'leg_id': None},
            'identity': {'role': 'strategy_client', 'principal_ref': CLIENT.principal_ref,
                         'actor_ref': CLIENT.actor_ref, 'delegate_ref': None}},
        'peer': {'role': 'service', 'principal_ref': SERVICE.principal_ref,
                 'actor_ref': SERVICE.actor_ref, 'delegate_ref': None},
        'requested_operations': sorted(OPS),
        'execution_time_policy': {'route': ROUTE, 'timezone': 'UTC',
                                  'format': 'date_hms_seconds_v1', 'schema_version': 1},
        'instruments_by_ref': {'rb': INSTRUMENT.to_dict()}}
    return raw


def _configured_client(root, endpoint, server_public, keys, journal_id, messages, controls):
    store = None
    try:
        from backtrader.stores.btapistore import BtApiStore
        path = Path(root) / 'configured-strategy'
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref=CLIENT.principal_ref,
            actor_ref=CLIENT.actor_ref, execution_domain_ref=DOMAIN, account_scope=ACCOUNT,
            strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        raw = _configured_raw(endpoint, journal_id)
        store = BtApiStore(config={'gateway_strategy': raw, 'contracts': {
            'rb': {'quantity_unit': 'lots', 'time_in_force': 'GFD'}}}, gateway_host=host,
                           gateway_security_profiles={'security': ClientCurveKeys(server_public, *keys)})
        data, broker, strategy = framework()
        broker.store = store
        broker.start()
        assert store.gateway_sequence is not None
        broker.cerebro.runningstrats = [strategy]
        broker.next()  # An idle strategy binds even without creating an order.
        assert broker._gateway_stream_binding.strategy is strategy
        import math
        assert math.isnan(broker.getcash()) and math.isnan(broker.getvalue())
        assert broker.gateway_financial_unavailable["position_price"] == "GATEWAY_STRATEGY_POSITION_PRICE_UNAVAILABLE"
        with pytest.raises(RuntimeError, match="GATEWAY_ACCOUNT_POSITION_UNAVAILABLE"):
            broker.getposition(data)
        assert store.contract_metadata['rb']['instrument_key'] == INSTRUMENT.to_dict()
        assert store.contract_metadata['rb']['gateway_rule_source'] == 'local_configuration'
        order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
        order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
        reserve_calls, reserve = [], store.gateway_api.reserve_order
        def tracked_reserve(*args, **kwargs):
            reserve_calls.append(True)
            return reserve(*args, **kwargs)
        store.gateway_api.reserve_order = tracked_reserve
        before_seq, before_pending = store.gateway_sequence.local_seq, host._store._load()
        with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
            broker.submit(order)
        assert store.gateway_sequence.local_seq == before_seq and host._store._load() == before_pending
        assert broker.get_notification() is None and order.status == order.Created and not reserve_calls
        messages.put(('configured-unqualified', os.getpid()))
    except BaseException:
        messages.put(('error', traceback.format_exc()))
    finally:
        if store is not None:
            try:
                store.stop(timeout=5)
            except BaseException:
                messages.put(('error', traceback.format_exc()))


def test_spawned_gateway_store_config_binds_and_rejects_unqualified_feed(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        endpoint = 'tcp://127.0.0.1:' + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gm, gc, cm, cc = ctx.Queue(), ctx.Queue(), ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_gateway, args=(str(tmp_path), endpoint, server_keys, client_keys, gm, gc))
    client = None
    server.start()
    try:
        ready = _message(gm, 'ready')
        client = ctx.Process(target=_configured_client,
            args=(str(tmp_path), endpoint, server_keys[0], client_keys, ready[2], cm, cc))
        client.start()
        assert _message(cm, 'configured-unqualified')[1] == client.pid
        _join(client)
    finally:
        if client is not None and client.is_alive():
            client.terminate()
            client.join(5)
        gc.put('stop')
        _join(server)
        assert _message(gm, 'closed') == ('closed', server.pid)
        for q in (gm, gc, cm, cc):
            q.close()


def _cerebro_client(root, endpoint, server_public, keys, journal_id, messages, controls):
    store = None
    try:
        import math
        import pandas as pd
        from backtrader.stores.btapistore import BtApiStore

        path = Path(root) / 'cerebro-strategy'
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref=CLIENT.principal_ref,
            actor_ref=CLIENT.actor_ref, execution_domain_ref=DOMAIN, account_scope=ACCOUNT,
            strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        store = BtApiStore(config={'gateway_strategy': _configured_raw(endpoint, journal_id),
            'contracts': {'rb': {'quantity_unit': 'lots', 'time_in_force': 'GFD'}}},
            gateway_host=host, gateway_security_profiles={'security': ClientCurveKeys(server_public, *keys)})

        class TestStrategy(bt.Strategy):
            def __init__(self):
                self.sent = False
                self.rejected = False
                self.notices = []
            def next(self):
                if self.sent:
                    return
                self.sent = True
                assert self.broker._gateway_stream_binding.strategy is self
                reserve_calls, reserve = [], store.gateway_api.reserve_order
                def tracked_reserve(*args, **kwargs):
                    reserve_calls.append(True)
                    return reserve(*args, **kwargs)
                store.gateway_api.reserve_order = tracked_reserve
                before_seq, before_pending = store.gateway_sequence.local_seq, host._store._load()
                with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
                    self.buy(size=2, price=10, exectype=bt.Order.Limit, offset='open',
                             quantity_unit='lots', time_in_force='GFD')
                assert (store.gateway_sequence.local_seq == before_seq
                        and host._store._load() == before_pending and not reserve_calls)
                self.rejected = True
            def notify_order(self, order):
                self.notices.append((order.status, order.executed.size))
            def stop(self):
                messages.put(('cerebro-result', self.rejected, self.notices,
                    self.broker.positions['rb'].size,
                    host.load_execution_checkpoint().acknowledged_sequence,
                    math.isnan(self.broker.getcash())))

        frame = pd.DataFrame({'open':[10.]*8, 'high':[11.]*8, 'low':[9.]*8,
                              'close':[10.]*8, 'volume':[1.]*8},
            index=pd.date_range('2030-01-01 09:00', periods=8, freq='min'))
        cerebro = bt.Cerebro(stdstats=False, runonce=False)
        broker = bt.brokers.BtApiBroker(store=store)
        cerebro.setbroker(broker)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name='rb')
        cerebro.addstrategy(TestStrategy)
        cerebro.run()
    except BaseException:
        messages.put(('error', traceback.format_exc()))
    finally:
        if store is not None and store.gateway_api is not None:
            try:
                store.stop(timeout=5)
            except BaseException:
                messages.put(('error', traceback.format_exc()))


def test_cerebro_binds_configured_gateway_and_rejects_unqualified_feed(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        endpoint = 'tcp://127.0.0.1:' + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gm, gc, cm, cc = ctx.Queue(), ctx.Queue(), ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_gateway, args=(str(tmp_path), endpoint, server_keys, client_keys, gm, gc))
    client = None
    server.start()
    try:
        ready = _message(gm, 'ready')
        client = ctx.Process(target=_cerebro_client,
            args=(str(tmp_path), endpoint, server_keys[0], client_keys, ready[2], cm, cc))
        client.start()
        result = _message(cm, 'cerebro-result')
        assert result[1:] == (True, [], 0, 0, True)
        _join(client)
    finally:
        if client is not None and client.is_alive():
            client.terminate()
            client.join(5)
        gc.put('stop')
        _join(server)
        assert _message(gm, 'closed') == ('closed', server.pid)
        for q in (gm, gc, cm, cc):
            q.close()
