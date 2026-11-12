"""Synthetic lost-reserve reply followed by a clean Gateway owner epoch.

Registry, services, guard and SQLite journals are real local components with
synthetic identities and fake provider callbacks. The fixture expires its one
known old-generation reservation before readiness; it is not a complete startup
sweep, a crash takeover, a deployed service, or real account evidence.
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
from bt_api_base.direct_write_protocol import NativeOrderIdentity, PreDispatchRecord, WriteOperation
from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_direct_protocol import gateway_payload_digest
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind, WireRole, WireScope,
)
from bt_api_execution.contracts import ExecutionScope
from bt_api_base.direct_cancel_protocol import PreparedCancelRequest
from bt_api_execution.gateway_delegate_host import ExecutionGatewayDelegateHost
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_cancel_journal import GatewayDirectCancelJournal
from bt_api_gateway.direct_cancel_dispatch import GatewayDirectCancelDispatcher
from bt_api_gateway.direct_delegation import GatewayDelegateGrant
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
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


def test_lost_reserve_freeze_then_clean_gateway_epoch(tmp_path, monkeypatch):
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
    reopen_anchor = None

    def factory():
        guard = LocalAccountSessionGuard(guard_dir, account, "synthetic-gateway-owner")
        try:
            return make_resources(guard)
        except BaseException as exc:
            raise GatewayOwnerStartupCleanupError(guard.release) from exc

    def make_resources(guard):
        generation = guard.acquire()
        if reopen_anchor is None:
            journal = GatewayDirectCommandJournal.create(tmp_path / "gateway.sqlite", account, generation=generation)
            journal.enable_controls(guard)
            journal.enable_strategy_ledger(guard)
            journal.enable_account_extensions(guard)
            journal.enable_parent_authority(guard)
        else:
            journal = GatewayDirectCommandJournal(tmp_path / "gateway.sqlite", account, generation=generation,
                expected_journal_id=reopen_anchor[0], minimum_revision=reopen_anchor[1],
                controls_enabled=True, strategy_ledger_enabled=True, account_extensions_enabled=True,
                parent_authority_enabled=True)
            # This one known test reservation is expired under the new guard
            # before readiness; this is not a general startup sweep.
            expired = journal.expire(strategy, "child-request-1", identity.principal_ref)
            assert expired.status == "EXPIRED" and expired.version == 2
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

        def synthetic_place(payload, port, account_scope):
            native = NativeOrderIdentity("CTP", "synthetic-native", {"trading_day": "20261109"}, 1)
            marker = port.commit(PreDispatchRecord(operation=WriteOperation.PLACE, host_scope=account_scope,
                exchange_name="CTP", symbol="rb", identity=native, target_identity=None,
                request_summary=payload, trading_day="20261109", session_generation=1,
                created_at_utc="synthetic"))
            with port.native_fence() as check:
                assert check() is True
                synthetic_calls.append("synthetic-place")
            return NativeDispatchOutcome(True, native, marker)

        dispatcher = GatewayDirectDispatcher(journal, "CTP", guard, synthetic_place,
            lambda _identity: ("synthetic-anchor",), lambda _row: True, claim_port=claim_port)

        def synthetic_cancel(target, symbol, port, account_scope):
            number = len(synthetic_cancels) + 1
            synthetic_cancels.append((number, target, symbol))
            prepared = PreparedCancelRequest(f"synthetic-cancel-{number}", target, symbol,
                "20261109", 1, {"request_id": number}, (f"synthetic-cancel-key-{number}",))
            marker = port.commit(PreDispatchRecord(WriteOperation.CANCEL, account_scope, "CTP",
                symbol, None, target, {}, prepared.trading_day, prepared.session_generation,
                "synthetic", prepared))
            return NativeDispatchOutcome(True, target, marker)

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
        lose_reply = [True]

        def envelope(operation, arguments):
            return wire_request(operation, {"registration_id": issued["registration_id"],
                "service_epoch": issued["service_epoch"], "instance_id": "instance",
                "arguments": arguments})

        def rpc(_mount, operation, arguments, **_kwargs):
            calls.append(operation)
            request = envelope(operation, arguments)
            response = registry.handle(identity.principal_ref, request)
            assert response["ok"], response
            responses.append((operation, response["result"]))
            if operation == "direct.delegated_reserve" and lose_reply[0]:
                lose_reply[0] = False
                raise TimeoutError("synthetic lost reserve reply after Gateway commit")
            return response["result"]

        monkeypatch.setattr(runtime, "call", rpc)
        store = SqliteExecutionStore(tmp_path / "execution.sqlite")
        lease = store.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
        old = ParentAuthority(store, scope, lease, admission=lambda _action, _value: True)
        old_client = GatewayParentServiceClient(runtime, route=route, host=old)
        old.bind_gateway(old_client)
        old.accept(parent)
        assert old.register("parent-1")["gateway_state"] == "ACCEPTED"
        request = OrderRequest(symbol="rb", side=Side.BUY, order_type=OrderType.LIMIT,
            quantity=Decimal("3"), account_id=account, client_order_id="child-1", price=Decimal("10"),
            idempotency_key="child-request-1", quantity_unit="lots", offset="open", exchange_id="SHFE")
        digest = gateway_payload_digest(request.to_dict())
        command = GatewayDelegatedCommand(account, strategy, domain, identity.principal_ref,
            identity.actor_ref, "execution", "synthetic-run", "child-request-1", digest,
            instrument, "g1", "parent-1", "child-1")
        old.prepare_child("parent-1", {"child_id": "child-1", "request_key": "child-request-1",
            "trading_day": "20261109", "offset": "open", "quantity": "3", "payload_digest": digest})
        old_host = ExecutionGatewayDelegateHost(old)
        old_delegate = GatewayDelegateServiceClient(runtime, route=route, host=old_host)

        # Reserve is durably handled by the actual service, then the transport
        # drops only its reply; dispatch never begins.
        lost = old.dispatch_child("parent-1", "child-1", command, request, old_delegate)
        assert lost.outcome == "UNKNOWN", lost
        assert calls[-1] == "direct.delegated_reserve"
        assert responses[-1][1]["state"] == "RESERVED"
        assert old_host.load_delegate_observation(command.request_key) is None
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            row = db.execute("SELECT reservation_id,digest,generation,status,version FROM direct_journal_commands WHERE request_key=?", (command.request_key,)).fetchone()
        assert row[1:] == (digest, owner.binding().generation, "RESERVED", 1)
        assert old.cancel("parent-1", "parent-cancel-1", 1)["cancel_state"] == "REQUESTED"
        frozen_row = store._connection.execute(
            "SELECT operation_id,frozen_json,intent_json FROM execution_parent_child_cancels WHERE parent_id=? AND child_id=?",
            ("parent-1", "child-1")).fetchone()
        frozen = json.loads(frozen_row["frozen_json"])
        assert frozen["phase"] == "RELEASE_PENDING"
        assert frozen["reservation_id"] == row[0] and frozen["payload_digest"] == digest
        assert frozen["cancel_operation_id"] == frozen_row["operation_id"]
        assert frozen_row["intent_json"] is None
        old_generation = owner.binding().generation
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            reopen_anchor = db.execute("SELECT journal_id,revision FROM direct_journal_meta WHERE account=?", (account,)).fetchone()
        assert parts["synthetic_calls"] == [] and parts["synthetic_cancels"] == []
        assert owner.close(2) and owner.closed
        registry.close()
        registry = None
        # The new factory expires the known old-generation reservation while
        # holding the same guard and before the owner reports ready.
        owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=2, busy_timeout_seconds=2)
        assert owner.start(2), owner.status()
        assert owner.binding().generation != old_generation
        assert owner.binding().journal_id == reopen_anchor[0]
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT reservation_id,digest,generation,status,version FROM direct_journal_commands WHERE request_key=?", (command.request_key,)).fetchone() == (row[0], digest, old_generation, "EXPIRED", 2)
        registry = ServiceRegistry(":memory:", service_id="synthetic-gateway",
            capabilities=(ServiceCapability("instance", "service.direct_write", operations | strategy_ops, writes),),
            grants={identity.principal_ref: (PrincipalGrant(identity, (
                ResourceGrant("instance", "service.direct_write", "scope", template, operations),)),),
                strategy_identity.principal_ref: (PrincipalGrant(strategy_identity, (
                ResourceGrant("instance", "service.direct_write", "scope", template, strategy_ops),)),)},
            policy_version="synthetic-policy", requirements_version="synthetic-requirements")
        service = GatewayParentService(GatewayParentSettings((grant,)), owner=owner, journal=parts["journal"],
                                       authority=parts["parent"], instance_id="instance", scope_ref="scope")
        service.configure(registry)
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
        binding = BindingSnapshot(issued["registration_id"], issued["service_epoch"], True, route.mount,
            route.service_id, route.instance_id, route.scope_ref, wire_scope, operations, True)
        before_calls = len(calls)
        result = old.advance_cancel_children("parent-1", old_delegate)
        assert len(result) == 1 and result[0].outcome == "OBSERVED"
        observed = result[0].observation.command
        assert observed.state == "EXPIRED" and observed.version == 2
        assert observed.reservation_id == row[0] and observed.digest == digest
        assert observed.owner_generation == owner.binding().generation
        assert observed.reservation_generation == old_generation
        assert calls[before_calls:] == ["direct.delegate_actor_status"]
        assert old_host.load_delegate_observation(command.request_key) == observed
        # The frozen release remains unresolved; replay queries only.
        replay = old.advance_cancel_children("parent-1", old_delegate)
        assert len(replay) == 1 and replay[0].outcome == "OBSERVED"
        assert replay[0].observation.command == observed
        assert calls[before_calls:] == ["direct.delegate_actor_status"] * 2
        assert parts["synthetic_calls"] == [] and parts["synthetic_cancels"] == []
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT status,version FROM direct_journal_commands WHERE request_key=?", (command.request_key,)).fetchone() == ("EXPIRED", 2)
            assert db.execute("SELECT COUNT(*) FROM direct_journal_releases").fetchone() == (0,)
        assert store._connection.execute("SELECT operation_id,frozen_json,intent_json FROM execution_parent_child_cancels WHERE parent_id=? AND child_id=?", ("parent-1", "child-1")).fetchone() == frozen_row
        child = store._connection.execute("SELECT state,filled_quantity FROM execution_parent_children WHERE parent_id=? AND child_id=?", ("parent-1", "child-1")).fetchone()
        assert tuple(child) == ("UNKNOWN", "0")
    finally:
        if store is not None:
            store.close()
        if registry is not None:
            registry.close()
        assert owner.close(2)
