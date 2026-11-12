"""Late delegated child dispatch after a synthetic writer generation change.

This is a conditional baseline, not the intended iteration 65 contract.  Both
SQLite owners and the Registry/service are real local components, but the
account, admission, registration, grant and transport are synthetic.  In
particular the Gateway registration is deliberately left valid after the
Execution writer changes.  No real account, CTP owner, provider call, network,
cross-process crash, or pre-existing retained host is involved.  The native
dispatcher and its claimed coverage are synthetic test substitutes.
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
from bt_api_execution.errors import WriterLeaseUnavailable
from bt_api_execution.gateway_delegate_host import ExecutionGatewayDelegateHost
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_delegation import GatewayDelegateGrant
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_delegate_service_client import GatewayDelegateRoute, GatewayDelegateServiceClient
from bt_api_py.gateway_delegation_service import (
    GatewayDelegationService, GatewayDelegationSettings, OPERATIONS as DELEGATE_OPERATIONS,
)
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
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


@pytest.mark.parametrize("revoke_before_delivery", [False, True], ids=["grant_active", "principal_revoked"])
def test_old_child_dispatch_arrives_after_synthetic_writer_takeover(tmp_path, monkeypatch, revoke_before_delivery):
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
        synthetic_calls = []

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
        parts.update(journal=journal, parent=authority, claims=claims, synthetic_calls=synthetic_calls)
        return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

    owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=2, busy_timeout_seconds=2)
    assert owner.start(2)
    registry = None
    store = None
    try:
        strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, "synthetic-strategy-principal", strategy)
        strategy_ops = frozenset({"direct.reserve"})
        operations = OPERATIONS | DELEGATE_OPERATIONS
        writes = frozenset({REGISTER, "direct.parent.cancel", "direct.reserve"}) | DELEGATE_OPERATIONS
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
            frozenset({instrument}), frozenset({"direct.reserve", "direct.dispatch"}))
        delegate = GatewayDelegationService(GatewayDelegationSettings((delegate_grant,),
            lambda value: value == instrument, parent_recheck=parts["parent"].recheck_child),
            owner=owner, journal=parts["journal"], instance_id="instance", scope_ref="scope")
        delegate.configure(registry)
        for operation in OPERATIONS:
            registry.register_handler("instance", operation,
                                      lambda ctx, args, operation=operation: service.handle(operation, ctx, args))
        for operation in DELEGATE_OPERATIONS:
            registry.register_handler("instance", operation,
                                      lambda ctx, args, operation=operation: delegate.handle(operation, ctx, args))
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
        captured, calls = [], []

        def envelope(operation, arguments):
            return wire_request(operation, {"registration_id": issued["registration_id"],
                "service_epoch": issued["service_epoch"], "instance_id": "instance",
                "arguments": arguments})

        def rpc(_mount, operation, arguments, **_kwargs):
            calls.append(operation)
            request = envelope(operation, arguments)
            if operation == "direct.delegated_dispatch":
                assert not captured
                captured.append(request)
                raise TimeoutError("synthetic transport holds the original dispatch request")
            response = registry.handle(identity.principal_ref, request)
            assert response["ok"], response
            return response["result"]

        monkeypatch.setattr(runtime, "call", rpc)
        store = SqliteExecutionStore(tmp_path / "execution.sqlite")
        old_lease = store.acquire_or_renew_lease(scope, "old-writer", ttl_ns=300_000_000_000)
        old = ParentAuthority(store, scope, old_lease, admission=lambda _action, _value: True)
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
        assert old.dispatch_child("parent-1", "child-1", command, request, old_delegate).outcome == "UNKNOWN"
        assert calls == [REGISTER, "direct.delegated_reserve", "direct.delegated_dispatch"] and len(captured) == 1
        assert old_host.load_delegate_intent("child-request-1").command == command
        assert old_host.load_delegate_observation("child-request-1").state == "RESERVED"
        assert old_host.load_delegate_dispatch_marker("child-request-1") is not None
        assert parts["synthetic_calls"] == []
        assert store.release_lease(scope, "old-writer", fencing_token=old_lease.fencing_token)
        new_lease = store.acquire_or_renew_lease(scope, "new-writer", ttl_ns=300_000_000_000)
        assert new_lease.fencing_token > old_lease.fencing_token
        with pytest.raises(WriterLeaseUnavailable):
            old.accept(parent)  # this enters the real writer-fenced transaction
        new = ParentAuthority(store, scope, new_lease, admission=lambda _action, _value: True)
        assert new.get("parent-1")["gateway_state"] == "ACCEPTED"
        child = store._connection.execute(
            "SELECT request_json,state FROM execution_parent_children WHERE parent_id=? AND child_id=?",
            ("parent-1", "child-1")).fetchone()
        assert child["state"] == "UNKNOWN"
        assert json.loads(child["request_json"])["request_key"] == "child-request-1"
        new_host = ExecutionGatewayDelegateHost(new)
        assert new_host.load_delegate_intent("child-request-1").command == command
        assert new_host.load_delegate_observation("child-request-1").state == "RESERVED"
        assert new_host.load_delegate_dispatch_marker("child-request-1") is not None
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT status FROM direct_journal_commands WHERE request_key=?", ("child-request-1",)).fetchone()[0] == "RESERVED"
        assert issued["registration_id"] in registry.active_registration_ids(instance_id="instance")

        # The exact old wire envelope arrives after the Execution lease changed;
        # the active-grant case deliberately does not revoke Registry authority.
        # The separate control revokes the synthetic principal through the real
        # Registry API; it does not claim local lease fencing caused the denial.
        if revoke_before_delivery:
            assert registry.revoke_principal(identity.principal_ref) is True
        delivered = registry.handle(identity.principal_ref, captured[0])
        if revoke_before_delivery:
            assert delivered["ok"] is False
            with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
                assert db.execute("SELECT state FROM direct_execution_parents WHERE parent_ref=?", ("parent-1",)).fetchone()[0] == "ACTIVE"
                assert db.execute("SELECT status FROM direct_journal_commands WHERE request_key=?", ("child-request-1",)).fetchone()[0] == "RESERVED"
            assert store._connection.execute(
                "SELECT state FROM execution_parent_children WHERE parent_id=? AND child_id=?",
                ("parent-1", "child-1")).fetchone()[0] == "UNKNOWN"
            assert calls.count("direct.delegated_dispatch") == 1
            assert parts["synthetic_calls"] == []
            return
        assert delivered["ok"], delivered
        result = delivered["result"]
        assert result["status"] == "QUEUED"
        assert result["request_key"] == "child-request-1"
        assert result["reservation_id"] == new_host.load_delegate_observation("child-request-1").reservation_id
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
                status = db.execute("SELECT status FROM direct_journal_commands WHERE request_key=?", ("child-request-1",)).fetchone()[0]
            if status in {"SENT", "NOT_SENT", "UNKNOWN"}:
                break
            time.sleep(.01)
        assert status == "SENT"
        assert parts["synthetic_calls"] == ["synthetic-place"]
        assert new_host.load_delegate_observation("child-request-1").state == "RESERVED"
        assert store._connection.execute(
            "SELECT state FROM execution_parent_children WHERE parent_id=? AND child_id=?",
            ("parent-1", "child-1")).fetchone()[0] == "UNKNOWN"
        assert calls.count("direct.delegated_dispatch") == 1

        # An exact dispatch payload under a fresh wire message retains the
        # original command identity; no SDK actor-status recovery is asserted.
        replay = registry.handle(identity.principal_ref,
            envelope("direct.delegated_dispatch", dict(captured[0].payload["arguments"])))
        assert replay["ok"] and replay["result"]["status"] == "OBSERVED"
        assert replay["result"]["state"] == "SENT"
        assert replay["result"]["reservation_id"] == result["reservation_id"]
        assert calls.count("direct.delegated_dispatch") == 1
        assert parts["synthetic_calls"] == ["synthetic-place"]
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT state FROM direct_execution_parents WHERE parent_ref=?", ("parent-1",)).fetchall() == [("ACTIVE",)]
            assert db.execute("SELECT status FROM direct_journal_commands WHERE request_key=?", ("child-request-1",)).fetchall() == [("SENT",)]
    finally:
        if store is not None:
            store.close()
        if registry is not None:
            registry.close()
        assert owner.close(2)
