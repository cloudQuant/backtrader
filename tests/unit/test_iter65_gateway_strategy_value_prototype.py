"""D63-44 synthetic snapshot -> Gateway Registry -> SDK -> BT Strategy.

The owner, SQLite journal, registry, financial client and BT getters are real.
The source verifier accepts controlled test inputs, and the in-process transport
is substituted; no market/provider/account authority or event-driven financial
reconstruction is established. No socket or external service is contacted.
"""

from contextlib import contextmanager
from dataclasses import replace
import itertools
from pathlib import Path
import sys
from types import SimpleNamespace

import backtrader as bt
import bt_api_base
import bt_api_gateway
import bt_api_py
import pytest

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind, WireRole, WireScope,
)
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_gateway.strategy_financial_ledger import StrategyFinancialSnapshot
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant, ServiceCapability, ServiceRegistry
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_stream_consumer import INSTRUMENT, framework

ROOT = Path(__file__).resolve().parents[3]
OP = "direct.strategy_financial"


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    for module in (bt, bt_api_base, bt_api_gateway, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), module.__file__
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(ROOT):
                escaped[name] = source
    assert not escaped, f"non-worktree imports: {escaped}"


def snapshot(journal, generation):
    names = ("budget", "adjustments", "realized_pnl", "unrealized_pnl", "fees", "margin", "reservations", "coverage")
    return StrategyFinancialSnapshot(account="acct", journal_id=journal.journal_id, strategy="s1",
        currency="CNY", revision=1, previous_digest=None, cut_ref="synthetic-cut-1",
        owner_generation=generation, source_refs=tuple((n, "synthetic-" + n) for n in sorted(names)),
        initial_budget="100000", adjustments="0", realized_pnl="2000", unrealized_pnl="3000",
        fees="100", margin="20000", reservations="10000")


def make_session(host, route):
    config = {"client_config_schema_version": 1, "process_role": "strategy_client",
        "registration": {"strategy_ref": route.scope.strategy_ref},
        "clients": {"gateway": {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": route.mount, "service_id": route.service_id, "instance_id": route.instance_id,
            "scope_ref": route.scope_ref, "account_ref": route.scope.account_ref,
            "transport_ref": "transport"}]}}},
        "communication": {"config_schema_version": 1, "profiles": {"transport": {
            "backend": "zmq", "config_schema_version": 1,
            "endpoints": {"rpc_connect": "tcp://127.0.0.1:12345"}, "security_profile_ref": "security"}}}}
    session = GatewayStrategyClientSession(parse_client_config(config), binding=host._binding,
        route=route, peer=WireIdentity(WireRole.SERVICE, "service", route.service_id),
        security_profiles={"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)},
        host=host, requested_operations=frozenset({OP}))
    return session, GatewayBtApi(session, exchange_name="CTP___FUTURE")


def test_synthetic_gateway_cuts_reach_real_strategy_getters(tmp_path, monkeypatch):
    (tmp_path / "guards").mkdir()
    holder = {"source_current": True}

    @contextmanager
    def synthetic_source_fence(account, strategy, currency):
        # Synthetic membership only. This proves no provider facts or freshness.
        yield lambda _db, item: (holder["source_current"] and
            (item.account, item.strategy, item.currency) == (account, strategy, currency))

    def factory():
        guard = LocalAccountSessionGuard(tmp_path / "guards", "acct", "owner")
        generation = guard.acquire()
        journal = GatewayDirectCommandJournal.create(tmp_path / "gateway.db", "acct", generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.enable_account_extensions(guard)
        journal.enable_parent_authority(guard)
        journal.enable_account_facts_financial(guard)
        journal.install_strategy_financial_port(guard=guard, source_fence=synthetic_source_fence)
        initial = snapshot(journal, generation)
        assert journal.append_strategy_financial(initial, guard=guard)
        def never_dispatch(*_args, **_kwargs):
            raise AssertionError("financial read prototype cannot dispatch")
        dispatcher = GatewayDirectDispatcher(journal, "CTP", guard, never_dispatch,
                                             lambda _: ("synthetic-anchor",), lambda _: False)
        holder.update(journal=journal, guard=guard, snapshot=initial)
        return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

    owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=1, busy_timeout_seconds=1)
    assert owner.start(2)
    registry = None
    try:
        identity = WireIdentity(WireRole.STRATEGY_CLIENT, "p", "s1")
        scope = WireScope("synthetic-domain", account_ref="acct", strategy_ref="s1", run_id="run1")
        grant_scope = WireScope("synthetic-domain", account_ref="acct", strategy_ref="s1")
        ops = frozenset({OP})
        registry = ServiceRegistry(":memory:", service_id="gateway-service",
            capabilities=(ServiceCapability("gateway", "service.direct_write", ops, frozenset()),),
            grants={"p": (PrincipalGrant(identity, (ResourceGrant("gateway", "service.direct_write",
                "scope", grant_scope, ops),)),)}, policy_version="p", requirements_version="r")
        service = GatewayDirectServiceBinding(holder["journal"],
            {"p": GatewayDirectGrant("s1", frozenset({"rb"}))}, owner=owner,
            strategy_financial_enabled=True)
        registry.register_handler("gateway", OP, lambda ctx, args: service.handle(OP, context=ctx, arguments=args))
        ids = itertools.count(1)
        def request(operation, payload):
            return WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                kind=WireMessageKind.REQUEST, message_id="message-" + str(next(ids)), correlation_id=None,
                identity=identity, scope=scope, operation=operation,
                schema_id="sdk.service.control" if operation.startswith("service.") else "sdk.service.call",
                schema_version=1, sent_at_utc="2026-10-13T12:00:00Z"), payload=payload)
        registered = registry.handle("p", request("service.register", {
            "registration_key": "synthetic-registration", "client_session_id": "synthetic-session",
            "instance_id": "gateway", "port": "service.direct_write", "scope_ref": "scope",
            "operations": (OP,)}))
        assert registered["ok"]
        rec = registered["result"]
        route = GatewayClientRoute("broker.direct_write", "gateway-service", "gateway", "scope", scope, identity)
        bt_dir = tmp_path / "bt-state"
        bt_dir.mkdir()
        state = StrategyStateDir.initialize(bt_dir)
        binding = GatewayCommandBinding(holder["journal"].journal_id, "acct", "s1", "p")
        GatewayPendingHost.upgrade_for_gateway(bt_dir, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(bt_dir, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref="p", actor_ref="s1",
            execution_domain_ref="synthetic-domain", account_scope="acct", strategy_scope="s1")
        host = GatewayPendingHost.upgrade_for_execution(bt_dir, state.strategy_uuid, binding, consumer_ref=consumer)
        session, api = make_session(host, route)
        reg = BindingSnapshot(rec["registration_id"], rec["service_epoch"], True, route.mount,
            route.service_id, route.instance_id, route.scope_ref, scope, ops, True)
        runtime_snapshot = RuntimeSnapshot("running", True, True, None, (reg,), 0, 0, identity, "run1")
        monkeypatch.setattr(session.runtime, "status", lambda: runtime_snapshot)
        calls = []
        def in_process_call(_mount, operation, arguments, **_kwargs):
            calls.append((operation, dict(arguments)))
            response = registry.handle("p", request(operation, {"registration_id": rec["registration_id"],
                "service_epoch": rec["service_epoch"], "instance_id": "gateway", "arguments": arguments}))
            assert response["ok"]
            return response["result"]
        monkeypatch.setattr(session.runtime, "call", in_process_call)
        data, broker, strategy = framework()
        broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
            gateway_strategy_config=SimpleNamespace(strategy_finance_currency="CNY"))
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
        assert strategy.get_strategy_value() == 104900.0
        assert strategy.get_strategy_cash() == 74900.0

        def publish(item):
            return owner.submit_service_call(
                lambda: holder["journal"].append_strategy_financial(item, guard=holder["guard"])
            ).result(timeout_seconds=2)
        first = holder["snapshot"]
        loss = replace(first, revision=2, previous_digest=first.digest, cut_ref="synthetic-cut-2",
                       unrealized_pnl="-3000")
        assert publish(loss)
        assert strategy.get_strategy_value() == 98900.0
        assert strategy.get_strategy_cash() == 68900.0
        released = replace(loss, revision=3, previous_digest=loss.digest, cut_ref="synthetic-cut-3",
                           reservations="0")
        assert publish(released)
        assert strategy.get_strategy_value() == 98900.0
        assert strategy.get_strategy_cash() == 78900.0
        assert calls == [(OP, {"currency": "CNY"})] * 6
        holder["source_current"] = False
        with pytest.raises(RuntimeError, match="GATEWAY_STRATEGY_CASH_UNAVAILABLE"):
            strategy.get_strategy_cash()
        with pytest.raises(RuntimeError, match="GATEWAY_STRATEGY_VALUE_UNAVAILABLE"):
            strategy.get_strategy_value()
    finally:
        if registry is not None:
            registry.close()
        assert owner.close(2)
