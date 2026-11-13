"""Synthetic key reuse and frozen release identity in local Gateway/Execution.

The Registry, Gateway services and both SQLite owners are real local components.
All identities, grants, transport and Execution admission are synthetic; no
provider, network, real authorization, account or crash claim is made.
"""

from decimal import Decimal
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import time

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_direct_protocol import gateway_payload_digest
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind, WireRole, WireScope,
)
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.gateway_delegate_host import ExecutionGatewayDelegateHost
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_cancel_journal import GatewayDirectCancelJournal
from bt_api_gateway.direct_cancel_dispatch import GatewayDirectCancelDispatcher
from bt_api_gateway.direct_delegation import GatewayDelegateGrant
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_delegate_service_client import GatewayDelegateRoute, GatewayDelegateServiceClient
from bt_api_py.gateway_delegation_service import (
    GatewayDelegationService, GatewayDelegationSettings, OPERATIONS as DELEGATE_OPERATIONS,
)
from bt_api_py.gateway_delegate_actor_service import GatewayDelegateActorService, OPERATIONS as ACTOR_OPERATIONS
from bt_api_py.gateway_direct_owner import (
    GatewayDirectOwner, GatewayDirectOwnerResources, GatewayOwnerStartupCleanupError,
)
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_dispatch_claim import (
    GATEWAY_DISPATCH_COVERAGE, GatewayDispatchClaimCoordinator, GatewayJournalDispatchChangePort,
    GatewayNativeDispatchClaimPort, seal_gateway_dispatch_coverage,
)
from bt_api_py.gateway_parent_client import GatewayParentServiceClient
from bt_api_py.gateway_parent_service import (
    GatewayParentGrant, GatewayParentService, GatewayParentSettings, OPERATIONS,
    REGISTER,
)
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant, ServiceCapability, ServiceRegistry
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot, ThreadedServiceClientRuntime


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    yield
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == "wt-iter65"
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(workspace):
                escaped[name] = source
    assert not escaped, escaped


def test_key_reuse_cannot_release_another_child(tmp_path, monkeypatch):
    account, strategy, domain = "synthetic-account", "synthetic-strategy", "synthetic-domain"
    identity = WireIdentity(WireRole.SERVICE, "synthetic-principal", "synthetic-actor")
    scope = ExecutionScope("FAKE", "test", account, strategy, "20261109")
    wire_scope = WireScope(domain, account_ref=account, strategy_ref=strategy, run_id="synthetic-run")
    template = WireScope(domain, account_ref=account, strategy_ref=strategy)
    instrument = MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb", "rb")
    parent = {
        "parent_ref": "parent-1", "registration_operation_id": "register-1",
        "risk_operation_id": "risk-1", "account_scope": account, "strategy_scope": strategy,
        "execution_domain_ref": domain, "instrument": instrument.to_dict(),
        "quantity": "5", "quantity_unit": "lots", "side": "buy", "offset": "open",
        "limit_price": "10", "creation_trading_day": "20261109",
        "allowed_trading_days": ["20261109"], "expires_at_ns": time.time_ns() + 60_000_000_000,
        "grant_revision": "g1", "plan_digest": "a" * 64, "plan_version": "v1",
        "target_position_ref": None, "risk_selected": False, "time_in_force": "DAY",
    }
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    parts = {}

    def factory():
        guard = LocalAccountSessionGuard(guard_dir, account, "synthetic-gateway-owner")
        try:
            return make_resources(guard)
        except BaseException as exc:
            raise GatewayOwnerStartupCleanupError(guard.release) from exc

    def make_resources(guard):
        generation = guard.acquire()
        journal = GatewayDirectCommandJournal.create(tmp_path / "gateway.sqlite", account, generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        authority = GatewayParentAuthority(journal, guard, now_ns=time.time_ns,
                                          trading_day=lambda: "20261109",
                                          transfer_completed=lambda _db, _spec: "0", same_day_only=True)

        claims, sealer = GatewayDispatchClaimCoordinator.with_coverage_sealer(account, generation)
        journal.install_dispatch_change_port(guard=guard, port=GatewayJournalDispatchChangePort(claims))
        # Synthetic coverage declaration: this is not evidence of a deployed
        # provider session, complete writer coverage, or live account safety.
        wired = frozenset(label for labels in GATEWAY_DISPATCH_COVERAGE.values() for label in labels)
        seal_gateway_dispatch_coverage(claims, sealer, wired=wired)
        claim_port = GatewayNativeDispatchClaimPort(claims, journal_id="synthetic-gateway-journal")
        synthetic_calls, synthetic_cancels = [], []

        def synthetic_place(*_args):
            synthetic_calls.append("unexpected")
            raise AssertionError("native place is outside this test")

        dispatcher = GatewayDirectDispatcher(journal, "CTP", guard, synthetic_place,
            lambda _identity: ("synthetic-anchor",), lambda _row: True, claim_port=claim_port)

        def synthetic_cancel(*_args):
            synthetic_cancels.append("unexpected")
            raise AssertionError("native cancel is outside this test")

        cancel_dispatcher = GatewayDirectCancelDispatcher(GatewayDirectCancelJournal(journal), dispatcher,
            guard, "CTP", synthetic_cancel, lambda _row: True)
        parts.update(journal=journal, parent=authority, claims=claims, synthetic_calls=synthetic_calls,
                     synthetic_cancels=synthetic_cancels)
        return GatewayDirectOwnerResources(dispatcher, journal, guard.release, cancel_dispatcher=cancel_dispatcher)

    owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=2, busy_timeout_seconds=2)
    assert owner.start(2)
    registry = None
    store = None
    try:
        strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, "synthetic-strategy-principal", strategy)
        strategy_ops = frozenset({"direct.reserve", "direct.delegated_cancel", "direct.delegated_cancel_status"})
        operations = OPERATIONS | DELEGATE_OPERATIONS | ACTOR_OPERATIONS
        writes = frozenset({REGISTER, "direct.parent.cancel", "direct.reserve", "direct.delegated_cancel",
                            "direct.delegate_actor_cancel", "direct.delegate_actor_release"}) | DELEGATE_OPERATIONS
        registry = ServiceRegistry(":memory:", service_id="synthetic-gateway",
            capabilities=(ServiceCapability("instance", "service.direct_write", operations | strategy_ops, writes),),
            grants={identity.principal_ref: (PrincipalGrant(identity, (
                ResourceGrant("instance", "service.direct_write", "scope", template, operations),)),),
                strategy_identity.principal_ref: (PrincipalGrant(strategy_identity, (
                ResourceGrant("instance", "service.direct_write", "scope", template, strategy_ops),)),)},
            policy_version="synthetic-policy", requirements_version="synthetic-requirements")
        grant = GatewayParentGrant(identity, account, strategy, domain, "execution", "g1",
                                   frozenset({instrument}), OPERATIONS)
        service = GatewayParentService(GatewayParentSettings((grant,)), owner=owner, journal=parts["journal"],
                                       authority=parts["parent"], instance_id="instance", scope_ref="scope")
        service.configure(registry)
        delegate_grant = GatewayDelegateGrant(identity, account, strategy, domain, "execution", "g1",
            frozenset({instrument}), frozenset({"direct.reserve", "direct.dispatch", "direct.command_status",
                "direct.cancel", "direct.cancel_status", "direct.release"}))
        delegate = GatewayDelegationService(GatewayDelegationSettings((delegate_grant,),
            lambda value: value == instrument, parent_recheck=parts["parent"].recheck_child),
            owner=owner, journal=parts["journal"], instance_id="instance", scope_ref="scope")
        delegate.configure(registry)
        actor_service = GatewayDelegateActorService(delegate,
            parent_cancel_recheck=parts["parent"].check_cancel_target,
            release_target_recheck=parts["parent"].check_release_target,
            parent_grant_resolver=lambda ctx, op: registry.gateway_parent_grant(
                instance_id="instance", scope_ref="scope", identity=ctx.identity, scope=ctx.scope, operation=op))
        strategy_service = GatewayDirectServiceBinding(parts["journal"], {
            strategy_identity.principal_ref: GatewayDirectGrant(strategy, frozenset({instrument.native_symbol}))},
            owner=owner, cancel_enabled=True)
        for operation in OPERATIONS:
            registry.register_handler("instance", operation,
                                      lambda ctx, args, operation=operation: service.handle(operation, ctx, args))
        for operation in DELEGATE_OPERATIONS:
            registry.register_handler("instance", operation,
                                      lambda ctx, args, operation=operation: delegate.handle(operation, ctx, args))
        for operation in ACTOR_OPERATIONS:
            registry.register_handler("instance", operation,
                                      lambda ctx, args, operation=operation: actor_service.handle(operation, ctx, args))
        for operation in ("direct.delegated_cancel", "direct.delegated_cancel_status"):
            registry.register_handler("instance", operation,
                lambda ctx, args, operation=operation: strategy_service.handle(operation, context=ctx, arguments=args))
        message_ids = itertools.count(1)

        def wire_request(operation, payload, *, actor=identity):
            return WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                kind=WireMessageKind.REQUEST, message_id="synthetic-message-" + str(next(message_ids)),
                correlation_id=None, identity=actor, scope=wire_scope, operation=operation,
                schema_id="sdk.service.control" if operation.startswith("service.") else "sdk.service.call",
                schema_version=1, sent_at_utc="2026-11-09T00:00:00Z"), payload=payload)

        strategy_registration = registry.handle(strategy_identity.principal_ref, wire_request("service.register", {
            "registration_key": "synthetic-strategy-registration", "client_session_id": "synthetic-strategy-session",
            "instance_id": "instance", "port": "service.direct_write", "scope_ref": "scope",
            "operations": tuple(strategy_ops)}, actor=strategy_identity))
        assert strategy_registration["ok"], strategy_registration
        registration = registry.handle(identity.principal_ref, wire_request("service.register", {
            "registration_key": "synthetic-registration", "client_session_id": "synthetic-session",
            "instance_id": "instance", "port": "service.direct_write", "scope_ref": "scope",
            "operations": tuple(operations)}))
        assert registration["ok"], registration
        issued = registration["result"]
        route = GatewayDelegateRoute("upstream.direct_write", "synthetic-gateway", "instance", "scope",
                                     wire_scope, identity)
        runtime = ThreadedServiceClientRuntime(lambda: None)
        binding = BindingSnapshot(issued["registration_id"], issued["service_epoch"], True, route.mount,
                                  route.service_id, route.instance_id, route.scope_ref, wire_scope, operations, True)
        monkeypatch.setattr(runtime, "status", lambda: RuntimeSnapshot(
            "running", True, True, None, (binding,), 0, 0, identity, "synthetic-run"))
        calls = []
        responses = []
        arguments_seen = []

        def envelope(operation, arguments):
            return wire_request(operation, {"registration_id": issued["registration_id"],
                "service_epoch": issued["service_epoch"], "instance_id": "instance",
                "arguments": arguments})

        def rpc(_mount, operation, arguments, **_kwargs):
            calls.append(operation)
            arguments_seen.append((operation, arguments))
            request = envelope(operation, arguments)
            response = registry.handle(identity.principal_ref, request)
            assert response["ok"], response
            responses.append((operation, response["result"]))
            return response["result"]

        monkeypatch.setattr(runtime, "call", rpc)
        from bt_api_execution.errors import InvalidStateTransition
        from bt_api_py.gateway_delegate_service_client import GatewayDelegateActorReleaseIntent

        store = SqliteExecutionStore(tmp_path / "execution.sqlite")
        lease = store.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        authority = ParentAuthority(store, scope, lease, admission=lambda _action, _value: True)
        authority.bind_gateway(GatewayParentServiceClient(runtime, route=route, host=authority))
        authority.accept(parent)
        assert authority.register("parent-1")["gateway_state"] == "ACCEPTED"
        request = OrderRequest(symbol="rb", side=Side.BUY, order_type=OrderType.LIMIT,
            quantity=Decimal("2"), account_id=account, client_order_id="synthetic-client",
            price=Decimal("10"), idempotency_key="shared-key", quantity_unit="lots",
            offset="open", exchange_id="SHFE")
        digest = gateway_payload_digest(request.to_dict())
        first = GatewayDelegatedCommand(account, strategy, domain, identity.principal_ref,
            identity.actor_ref, "execution", "synthetic-run", "shared-key", digest,
            instrument, "g1", "parent-1", "child-1")
        second = GatewayDelegatedCommand(account, strategy, domain, identity.principal_ref,
            identity.actor_ref, "execution", "synthetic-run", "shared-key", digest,
            instrument, "g1", "parent-1", "child-2")
        for child_id in ("child-1", "child-2"):
            result = authority.prepare_child("parent-1", {"child_id": child_id,
                "request_key": "shared-key", "trading_day": "20261109", "offset": "open",
                "quantity": "2", "payload_digest": digest})
            assert result["state"] == "PREPARED"
        host = ExecutionGatewayDelegateHost(authority)
        client = GatewayDelegateServiceClient(runtime, route=route, host=host)
        assert authority.claim_child("parent-1", "child-1")["request_key"] == "shared-key"
        reserved = client.reserve(first, request)
        assert reserved.outcome == "OBSERVED" and reserved.observation.state == "RESERVED"
        assert calls == [REGISTER, "direct.delegated_reserve"]
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            row = db.execute("SELECT reservation_id,status,version FROM direct_journal_commands WHERE request_key=?",
                             ("shared-key",)).fetchone()
        assert row == (reserved.observation.reservation_id, "RESERVED", 1)
        before = calls.copy()
        collision = authority.dispatch_child("parent-1", "child-2", second, request, client)
        assert (collision.outcome, collision.code) == ("TRANSPORT_NOT_STARTED", "INTENT_NOT_DURABLE")
        assert calls == before and host.load_delegate_intent("shared-key").command == first
        observed = client.actor_status("shared-key")
        assert observed.outcome == "OBSERVED"
        assert observed.observation.command == reserved.observation
        actor_args = arguments_seen[-1]
        assert actor_args[0] == "direct.delegate_actor_status"
        assert GatewayDelegatedCommand.from_mapping(actor_args[1]["command"]) == first
        assert first.child_id == "child-1" and second.child_id == "child-2"
        cancelled = authority.cancel("parent-1", "parent-cancel-1", 1)
        assert cancelled["cancel_state"] == "REQUESTED"
        frozen_rows = store._connection.execute(
            "SELECT child_id,operation_id,frozen_json FROM execution_parent_child_cancels WHERE parent_id=?",
            ("parent-1",)).fetchall()
        assert len(frozen_rows) == 1 and frozen_rows[0]["child_id"] == "child-1"
        frozen = json.loads(frozen_rows[0]["frozen_json"])
        assert frozen["phase"] == "RELEASE_PENDING" and frozen["child_id"] == "child-1"
        assert frozen["request_key"] == "shared-key" and frozen["reservation_id"] == row[0]
        assert json.loads(cancelled["cancel_receipt_json"])["result"]["targets"] == [frozen]

        # Try the second command identity against the first child's real target.
        # This is only a locally constructed invalid request; no target for the
        # second child is invented or inserted into either journal.
        wrong = GatewayDelegateActorReleaseIntent("shared-key", frozen["cancel_operation_id"],
            second.digest, row[0], digest, identity.principal_ref, frozen["target_version"])
        before = calls.copy()
        with pytest.raises(InvalidStateTransition, match="release intent differs from frozen Gateway identity"):
            host.save_delegate_release_intent(wrong)
        assert host.load_delegate_release_intent(frozen["cancel_operation_id"]) is None
        missing = client.release_actor(observed.observation, operation_id="unfrozen-child-2")
        assert (missing.outcome, missing.code) == ("TRANSPORT_NOT_STARTED", "RELEASE_NOT_DURABLE")
        assert calls == before

        # Advance only the real Gateway-frozen child; its local terminal state
        # follows the actual in-process release plus synthetic admission recheck.
        results = authority.advance_cancel_children("parent-1", client)
        assert len(results) == 1 and results[0].outcome == "OBSERVED"
        assert results[0].state == "RELEASED" and results[0].reservation_id == row[0]
        assert calls[len(before):] == ["direct.delegate_actor_status", "direct.delegate_actor_release",
                                       "direct.delegate_actor_release_status"]
        children = store._connection.execute(
            "SELECT child_id,request_json,quantity,state,filled_quantity FROM execution_parent_children "
            "WHERE parent_id=? ORDER BY child_id", ("parent-1",)).fetchall()
        assert [(r["child_id"], r["quantity"], r["state"], r["filled_quantity"]) for r in children] == [
            ("child-1", "2", "TERMINAL", "0"), ("child-2", "2", "UNKNOWN", "0")]
        assert all(json.loads(r["request_json"])["request_key"] == "shared-key" for r in children)
        assert store._connection.execute(
            "SELECT COUNT(*) FROM execution_parent_child_evidence WHERE parent_id=? AND child_id=?",
            ("parent-1", "child-2")).fetchone()[0] == 0
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT status,version FROM direct_journal_commands WHERE request_key=?",
                              ("shared-key",)).fetchone() == ("RELEASED", 2)
            assert db.execute("SELECT COUNT(*) FROM direct_execution_parent_cancel_targets WHERE child_id=?",
                              ("child-2",)).fetchone() == (0,)
        assert parts["synthetic_calls"] == [] and parts["synthetic_cancels"] == []
        store.close()
        store = SqliteExecutionStore(tmp_path / "execution.sqlite")
        assert [tuple(r) for r in store._connection.execute(
            "SELECT child_id,quantity,state,filled_quantity FROM execution_parent_children "
            "WHERE parent_id=? ORDER BY child_id", ("parent-1",)).fetchall()] == [
            ("child-1", "2", "TERMINAL", "0"), ("child-2", "2", "UNKNOWN", "0")]
    finally:
        if store is not None:
            store.close()
        if registry is not None:
            registry.close()
        assert owner.close(2)
