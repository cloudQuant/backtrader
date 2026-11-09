"""BT execution checkpoint against a spawned synthetic Gateway over CURVE.

The caller-owned projection below is only a durable test snapshot: no BT
Order, Position, Trade, provider, or real account is exercised here.
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import sys
import threading
from pathlib import Path

import pytest
import zmq
from bt_api_base.direct_write_protocol import (
    DirectExecutionEventKind, NativeOrderIdentity, PreDispatchRecord, WriteOperation,
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

from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from bt_api_py.direct_write import project_direct_strong_identity_keys
from bt_api_py.gateway_direct_client import GatewayClientRoute, GatewayDirectClient
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_stream_client import GatewayExecutionStreamClient
from bt_api_py.gateway_execution_stream_service import GatewayExecutionStreamService, STREAM_OPERATIONS
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
from bt_api_py.service_runtime_thread import ThreadedServiceClientRuntime
from tests.unit.live_state.test_gateway_pending_client import (
    ACCOUNT, CLIENT, DOMAIN, OPS, SERVICE, _client_config, _endpoint, _request, _sent, _service_config,
)

CLIENT_B = WireIdentity(WireRole.STRATEGY_CLIENT, "principal-b", "strategy-b")
EVENT_OPS = OPS | STREAM_OPERATIONS
INSTRUMENT = MarketInstrumentKey("synthetic", "venue", "paper", "future", "rb", "rb")


def _gateway_process(root, endpoint, server_keys, clients, messages, controls):
    root = Path(root)
    owner = host = stream = None
    try:
        (root / "guard").mkdir()
        resources = []

        def owner_factory():
            guard = LocalAccountSessionGuard(root / "guard", ACCOUNT, "synthetic-owner")
            journal = GatewayDirectCommandJournal.create(root / "journal.sqlite", ACCOUNT, generation=guard.acquire())
            ledger = GatewayDirectExecutionLedger(journal, guard)

            def native(payload, port, host_scope):
                key = payload["idempotency_key"]
                identity = NativeOrderIdentity("TEST", "native-" + key,
                    {"inst_id": "rb", "trading_day": "20300101"}, 1)
                record = PreDispatchRecord(operation=WriteOperation.PLACE, host_scope=host_scope,
                    exchange_name="TEST", symbol=payload["symbol"], identity=identity,
                    target_identity=None, request_summary=payload, trading_day="20300101",
                    session_generation=1, created_at_utc="synthetic")
                marker = port.commit(record)
                return NativeDispatchOutcome(marker is not None, identity, marker)

            from tests.unit.live_state._gateway_claim_support import SyntheticClaimPort, claiming

            # Decision B: no dispatch without a claim port.
            dispatcher = GatewayDirectDispatcher(journal, "TEST", guard, claiming(native),
                lambda identity: project_direct_strong_identity_keys(identity, day_scoped_ids=True), lambda _: True,
                claim_port=SyntheticClaimPort())
            resources.append((journal, ledger))
            return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

        owner = GatewayDirectOwner(owner_factory, queue_size=8,
            max_queue_wait_seconds=10, busy_timeout_seconds=10)
        assert owner.start(10)
        journal, ledger = resources[0]
        identities = (CLIENT, CLIENT_B)
        stream = GatewayExecutionStreamService(ledger, journal,
            {item.principal_ref: item.actor_ref for item in identities}, execution_domain_ref=DOMAIN)
        binding = GatewayDirectServiceBinding(journal,
            {item.principal_ref: GatewayDirectGrant(item.actor_ref, frozenset({"rb"})) for item in identities},
            owner=owner, execution_stream=stream, execution_domain_ref=DOMAIN)
        grants = {}
        for identity in identities:
            scope = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=identity.actor_ref)
            resource = ResourceGrant("gateway-a", "service.direct_write", "scope-a", scope, EVENT_OPS)
            grants[identity.principal_ref] = (PrincipalGrant(identity, (resource,)),)
        authority = TrustedServiceAuthority(identity=SERVICE, scope=WireScope(DOMAIN), scope_ref="scope-a",
            scope_version="scope-v1", security_ref="security-a", security_version="security-v1",
            registration_policy_ref="direct-policy-v1", registration_policy_version="direct-policy-v1",
            service_requirements_ref="direct-requirements-v1", service_requirements_version="direct-requirements-v1",
            curve_public_key=server_keys[0], curve_secret_key=server_keys[1],
            principals={key[0]: identity.principal_ref for key, identity in zip(clients, identities)}, grants=grants)
        host = ServiceHost(_service_config(endpoint), authority, root / "registry.sqlite",
            lambda *_: ComponentResources.borrowed({"binding": binding}, ready=lambda: True))
        host.start()
        messages.put(("ready", os.getpid(), journal.journal_id))
        while True:
            try:
                command = controls.get_nowait()
            except queue.Empty:
                command = None
            if command == "stop":
                break
            if isinstance(command, tuple) and command[0] == "fact":
                _, key, trade = command
                def ingest():
                    identity = NativeOrderIdentity("TEST", "native-" + key,
                        {"inst_id": "rb", "trading_day": "20300101"}, 1)
                    keys = project_direct_strong_identity_keys(identity, day_scoped_ids=True)
                    fact = GatewayReturnFact(ACCOUNT, "TEST", INSTRUMENT, "20300101",
                        DirectExecutionEventKind.TRADE, "synthetic-" + trade,
                        identity=identity, identity_keys=keys, binding_keys=keys, venue_key=keys[0],
                        trade_key=("venue", trade), side="buy", offset="open",
                        trade_quantity="0.25", trade_price="10")
                    return ledger.ingest(fact)
                result = owner.submit_service_call(ingest).result(timeout_seconds=5)
                messages.put(("fact", result.disposition, result.event_sequence))
            host.serve_once(10)
    except BaseException as error:
        import traceback
        messages.put(("error", type(error).__name__, traceback.format_exc()))
    finally:
        try:
            if host is not None and host.state == "started":
                host.close()
            if stream is not None:
                assert stream.close()
            if owner is not None:
                assert owner.close(10)
            messages.put(("closed", os.getpid()))
        except BaseException as error:
            messages.put(("cleanup_error", type(error).__name__, str(error)))


@pytest.fixture
def gateway(tmp_path):
    # pytest importlib names this module live_state.*; spawn needs its parent.
    test_root = str(Path(__file__).resolve().parent.parent)
    if test_root not in sys.path:
        sys.path.insert(0, test_root)
    context = multiprocessing.get_context("spawn")
    messages, controls = context.Queue(), context.Queue()
    server_keys = zmq.curve_keypair()
    clients = (zmq.curve_keypair(), zmq.curve_keypair())
    endpoint = _endpoint()
    child = context.Process(target=_gateway_process,
        args=(str(tmp_path), endpoint, server_keys, clients, messages, controls))
    child.start()
    runtimes = []
    drop_ack, ack_calls = threading.Event(), []
    try:
        ready = messages.get(timeout=15)
        assert ready[:2] == ("ready", child.pid) and child.pid != os.getpid(), ready
        journal_id = ready[2]

        def connect(identity, run, *, recovery=False):
            index = 0 if identity == CLIENT else 1
            raw = _client_config(endpoint).to_public_dict()
            raw["registration"]["strategy_ref"] = identity.actor_ref
            scope = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=identity.actor_ref, run_id=run)
            binding = GatewayCommandBinding(journal_id, ACCOUNT, identity.actor_ref, identity.principal_ref)
            route = GatewayClientRoute("broker.direct_write", SERVICE.actor_ref, "gateway-a", "scope-a", scope, identity)
            operations = STREAM_OPERATIONS | ({"direct.command_status"} if recovery else OPS)

            def factory():
                transport = ZmqTransportFactory({"security-a": ClientCurveKeys(server_keys[0], *clients[index])})
                class DropAck:
                    def __init__(self, wrapped):
                        self._wrapped = wrapped
                    def request(self, request, *, timeout):
                        response = self._wrapped.request(request, timeout=timeout)
                        if request.header.operation == "direct.events.ack":
                            ack_calls.append((identity.principal_ref, request.payload["arguments"]["sequence"]))
                            if identity == CLIENT and drop_ack.is_set():
                                drop_ack.clear()
                                raise TimeoutError("synthetic lost ACK response")
                        return response
                    def close(self):
                        self._wrapped.close()
                return ServiceClientRuntime(parse_client_config(raw), identity=identity,
                    scope_resolver=lambda _: WireScope(DOMAIN, account_ref=ACCOUNT),
                    peer_resolver=lambda _: SERVICE, transport_factory=lambda *args: DropAck(transport(*args)),
                    run_id=run, requested_operations={"broker.direct_write": frozenset(operations)})

            runtime = ThreadedServiceClientRuntime(factory)
            runtimes.append(runtime)
            runtime.start(timeout_seconds=10)
            return runtime, route, binding, GatewayExecutionStreamClient(runtime, binding=binding, route=route)

        def fact(key, trade):
            controls.put(("fact", key, trade))
            result = messages.get(timeout=5)
            assert result[:2] == ("fact", "ATTRIBUTED"), result
            return result[2]

        yield connect, fact, drop_ack, ack_calls
    finally:
        errors = []
        for runtime in reversed(runtimes):
            try:
                result = runtime.close(timeout_seconds=10)
                if result.state != "closed" or result.thread_alive:
                    errors.append((result.state, result.thread_alive))
            except Exception as error:
                errors.append((type(error).__name__, str(error)))
        controls.put("stop")
        child.join(15)
        if child.is_alive():
            child.terminate()
            child.join(5)
            errors.append("synthetic gateway required termination")
        assert child.exitcode == 0
        try:
            closed = messages.get(timeout=3)
        except queue.Empty:
            closed = None
        assert closed == ("closed", child.pid), closed
        assert not errors, errors


def _consumer(identity):
    return gateway_execution_consumer_ref(principal_ref=identity.principal_ref,
        actor_ref=identity.actor_ref, execution_domain_ref=DOMAIN, account_scope=ACCOUNT,
        strategy_scope=identity.actor_ref)


def _host(tmp_path, name, binding, consumer):
    path = tmp_path / name
    path.mkdir()
    state = StrategyStateDir.initialize(path)
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    return state, GatewayPendingHost.upgrade_for_execution(state.strategy_dir, state.strategy_uuid,
        binding, consumer_ref=consumer, max_events=16, max_event_bytes=100_000, max_projection_bytes=100_000)


def _place(runtime, route, binding, host, key):
    client = GatewayDirectClient(runtime, binding=binding, route=route, host=host)
    assert client.reserve(_request(key), ttl_seconds=30).outcome == "OBSERVED"
    assert client.dispatch(key).outcome == "QUEUED"
    record = _sent(client, key)
    assert record.native_identity.client_order_id == "native-" + key
    return client, record


def _seed_three(gateway, tmp_path):
    connect, fact, _, _ = gateway
    runtime_a, route_a, binding_a, stream_a = connect(CLIENT, "run-a")
    runtime_b, route_b, binding_b, stream_b = connect(CLIENT_B, "run-b")
    state_a, host_a = _host(tmp_path, "strategy-a", binding_a, _consumer(CLIENT))
    state_b, host_b = _host(tmp_path, "strategy-b", binding_b, _consumer(CLIENT_B))
    client_a, record_a = _place(runtime_a, route_a, binding_a, host_a, "a")
    _place(runtime_b, route_b, binding_b, host_b, "b")
    assert [fact("a", "one"), fact("b", "two"), fact("a", "three")] == [1, 2, 3]
    return (runtime_a, route_a, binding_a, stream_a, state_a, host_a, client_a, record_a), (stream_b, host_b)


def test_sparse_pages_snapshot_ack_loss_and_reopen(gateway, tmp_path, monkeypatch):
    (runtime, route, binding, stream, state, host, client, record), (other_stream, other_host) = _seed_three(gateway, tmp_path)
    connect, _, drop_ack, ack_calls = gateway
    original_result = stream.read_after()
    assert original_result.outcome == "OBSERVED"
    page = original_result.page
    other = other_stream.read_after().page
    assert page.consumer_ref == _consumer(CLIENT) and [e.sequence for e in page.events] == [1, 3]
    assert other.consumer_ref == _consumer(CLIENT_B) and [e.sequence for e in other.events] == [2]
    assert all(e.command_principal == CLIENT.principal_ref for e in page.events)
    assert all(e.command_principal == CLIENT_B.principal_ref for e in other.events)
    initial = host.load_execution_checkpoint()
    # A genuine later query returns only sequence 3; its actual request cursor
    # must not be relabelled as the complete initial page.
    skipped = stream.read_after(after_sequence=1, expected_epoch=page.epoch)
    assert skipped.outcome == "OBSERVED" and [event.sequence for event in skipped.page.events] == [3]
    assert skipped.request_context.binding == binding
    assert skipped.request_context.consumer_ref == page.consumer_ref
    assert skipped.request_context.after_sequence == 1
    assert skipped.request_context.expected_epoch == page.epoch and skipped.request_context.limit == 256
    assert original_result.request_context.binding == binding
    assert original_result.request_context.consumer_ref == page.consumer_ref
    assert original_result.request_context.after_sequence == 0
    assert original_result.request_context.expected_epoch is None and original_result.request_context.limit == 256
    with pytest.raises(ValueError, match="EXECUTION_SEQUENCE_CONFLICT"):
        host.ingest_execution_result(skipped, expected_revision=initial.revision)
    assert host.load_execution_checkpoint() == initial
    assert host.read_execution_events() == () and ack_calls == []
    saved = host.ingest_execution_result(original_result, expected_revision=initial.revision)
    assert saved.stored_sequence == 3 and saved.applied_sequence == saved.acknowledged_sequence == 0
    assert ack_calls == []
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.read_execution_events() == page.events
    assert reopened.load_intent("a") == host.load_intent("a")
    assert reopened.load_record("a") == record
    original = reopened.load_execution_checkpoint()
    replayed = reopened.ingest_execution_result(original_result, expected_revision=original.revision)
    assert reopened.read_execution_events(after_sequence=0) == page.events
    assert replayed.stored_sequence == 3
    assert ack_calls == []

    import backtrader.live_state.pending as pending_module
    before = Path(state.pending.path).read_bytes()
    with monkeypatch.context() as patch:
        def fail_write(*_args, **_kwargs):
            raise OSError("synthetic projection commit failure")
        patch.setattr(pending_module, "atomic_write_json", fail_write)
        with pytest.raises((OSError, ValueError)):
            reopened.commit_execution_projection(1, {"schema_version": 1, "state": {"seen": [1]}},
                expected_revision=replayed.revision, expected_applied_sequence=0)
    assert Path(state.pending.path).read_bytes() == before and ack_calls == []
    snapshot = reopened.commit_execution_projection(1, {"schema_version": 1, "state": {"seen": [1]}},
        expected_revision=replayed.revision, expected_applied_sequence=0)
    assert snapshot.applied_sequence == 1 and snapshot.acknowledged_sequence == 0
    first = stream.ack(1, page.epoch)
    assert first.outcome == "OBSERVED"
    recorded = reopened.record_execution_ack(first.progress)
    assert recorded.acknowledged_sequence == 1
    applied = reopened.commit_execution_projection(3, {"schema_version": 1, "state": {"seen": [1, 3]}},
        expected_revision=recorded.revision, expected_applied_sequence=1)
    assert applied.applied_sequence == 3
    drop_ack.set()
    lost = stream.ack(3, page.epoch)
    assert lost.outcome == "UNKNOWN"
    assert reopened.load_execution_checkpoint().acknowledged_sequence == 1
    remote_after_loss = stream.progress()
    assert remote_after_loss.outcome == "OBSERVED" and remote_after_loss.progress.acknowledged_sequence == 3
    duplicate = stream.ack(3, page.epoch)
    assert duplicate.outcome == "OBSERVED" and duplicate.progress.acknowledged_sequence == 3
    checkpoint = reopened.record_execution_ack(duplicate.progress)
    assert checkpoint.applied_sequence == checkpoint.acknowledged_sequence == 3
    assert [x for x in ack_calls if x[0] == CLIENT.principal_ref] == [(CLIENT.principal_ref, 1), (CLIENT.principal_ref, 3), (CLIENT.principal_ref, 3)]
    assert other_host.load_execution_checkpoint().applied_sequence == 0
    original_intent = reopened.load_intent("a")
    assert runtime.close(timeout_seconds=10).state == "closed"
    runtime2, route2, binding2, recovered = connect(CLIENT, "run-restarted", recovery=True)
    assert binding2 == binding
    again = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert again.load_execution_checkpoint().consumer_ref == page.consumer_ref
    assert again.load_execution_checkpoint().projection == {"schema_version": 1, "state": {"seen": [1, 3]}}
    assert again.load_intent("a") == original_intent
    assert again.load_record("a") == record
    assert recovered.progress().progress.acknowledged_sequence == 3
    assert GatewayDirectClient(runtime2, binding=binding, route=route2, host=again).status("a").record == record


def test_server_ahead_of_applied_projection_is_rejected(gateway, tmp_path):
    (_, _, _, stream, _, host, _, _), _ = _seed_three(gateway, tmp_path)
    result = stream.read_after()
    page = result.page
    initial = host.load_execution_checkpoint()
    stored = host.ingest_execution_result(result, expected_revision=initial.revision)
    applied = host.commit_execution_projection(1, {"schema_version": 1, "state": {"seen": [1]}},
        expected_revision=stored.revision, expected_applied_sequence=0)
    # Deliberately advance the server beyond the local applied snapshot.
    ahead = stream.ack(3, page.epoch)
    assert ahead.outcome == "OBSERVED" and ahead.progress.acknowledged_sequence == 3
    with pytest.raises(ValueError):
        host.record_execution_ack(ahead.progress)
    after = host.load_execution_checkpoint()
    assert after.applied_sequence == applied.applied_sequence == 1
    assert after.acknowledged_sequence == 0


def test_page_waits_for_original_command_identity_before_persisting(gateway, tmp_path):
    """A page is never advanced past a fact whose native identity is not yet local."""
    connect, fact, _, ack_calls = gateway
    runtime, route, binding, stream = connect(CLIENT, "run-late")
    _, host = _host(tmp_path, "strategy-late", binding, _consumer(CLIENT))
    client = GatewayDirectClient(runtime, binding=binding, route=route, host=host)
    assert client.reserve(_request("late"), ttl_seconds=30).outcome == "OBSERVED"
    assert client.dispatch("late").outcome == "QUEUED"
    assert fact("late", "late-trade") == 1
    result = stream.read_after()
    page = result.page
    assert [event.sequence for event in page.events] == [1]
    assert host.load_record("late").native_identity is None
    checkpoint = host.load_execution_checkpoint()
    with pytest.raises(ValueError, match="GATEWAY_EXECUTION_IDENTITY_REQUIRED"):
        host.ingest_execution_result(result, expected_revision=checkpoint.revision)
    assert host.load_execution_checkpoint() == checkpoint
    assert host.read_execution_events() == () and ack_calls == []
    assert _sent(client, "late").native_identity.client_order_id == "native-late"
    reread_result = stream.read_after()
    reread = reread_result.page
    assert reread.events == page.events and reread.epoch == page.epoch
    saved = host.ingest_execution_result(reread_result, expected_revision=checkpoint.revision)
    assert saved.stored_sequence == 1 and saved.applied_sequence == 0
    assert host.read_execution_events() == page.events and ack_calls == []
