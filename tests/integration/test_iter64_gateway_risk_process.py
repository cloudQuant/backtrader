"""Iteration 64: a BT order placed through a stand-in Risk to a spawned Gateway, then followed.

INTEGRATION_SIM: a spawned loopback Gateway (63.13 composition, synthetic dispatcher and
synthetic return facts, temporary SQLite) with a Risk delegate grant; in this process the
real BT broker and stream consumer, the real SDK facade and a stand-in Risk that answers
risk.order.reserve/dispatch by forwarding as the delegate with GatewayDelegateServiceClient
over CURVE. The Risk service transport itself is replaced in-process (the Risk host is built
separately). No provider session, account or venue.
"""
from __future__ import annotations

import hashlib
import multiprocessing
import os
import queue
import socket
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pytest

zmq = pytest.importorskip("zmq")

from bt_api_base.account_protocol import (  # noqa: E402
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountResourceKey,
)
from bt_api_base.direct_cancel_protocol import PreparedCancelRequest  # noqa: E402
from bt_api_base.direct_write_protocol import (  # noqa: E402
    DirectExecutionEventKind,
    DirectOrderStatus,
    NativeOrderIdentity,
    PreDispatchRecord,
    WriteOperation,
)
from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand  # noqa: E402
from bt_api_base.gateway_direct_protocol import (  # noqa: E402
    GatewayCommandBinding,
    gateway_payload_digest,
)
from bt_api_base.gateway_execution_protocol import GatewayReturnFact  # noqa: E402
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref  # noqa: E402
from bt_api_base.market_protocol import MarketInstrumentKey  # noqa: E402
from bt_api_base.risk_service_protocol import RiskOrderResult  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402

ACCOUNT, DOMAIN, RUN, ROUTE = "account-a", "paper:demo", "strategy-run", "CTP"
SERVICE = WireIdentity(WireRole.SERVICE, "gateway-principal", "gateway-service")
STRATEGY = WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a")
RISK = WireIdentity(WireRole.SERVICE, "risk-principal", "risk-service")
SCOPE = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY.actor_ref, run_id=RUN)
ACCOUNT_ONLY = WireScope(DOMAIN, account_ref=ACCOUNT)
INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb", "rb")
LOGICAL = frozenset({"direct.reserve", "direct.dispatch", "direct.command_status", "direct.cancel",
                     "direct.cancel_status", "direct.release"})
TRADING_DAY = "20300101"


def _free_endpoint():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return "tcp://127.0.0.1:%d" % sock.getsockname()[1]


def _strategy_ops():
    from bt_api_py.gateway_direct_service import EVENT_OPERATIONS
    return frozenset({"direct.delegated_command_status", "direct.delegated_cancel",
                      "direct.delegated_cancel_status"}) | EVENT_OPERATIONS


def _delegate_ops():
    from bt_api_py.gateway_delegate_actor_service import OPERATIONS as ACTOR_OPERATIONS
    return frozenset({"direct.delegated_reserve", "direct.delegated_dispatch"}) | ACTOR_OPERATIONS


def _service_config(endpoint):
    from bt_api_py.service_config import parse_service_config
    return parse_service_config({
        "service_config_schema_version": 1, "process_role": "service",
        "service_id": SERVICE.actor_ref, "scope_ref": "scope-a", "transport_ref": "server-transport",
        "registration_policy_ref": "direct-policy-v1", "service_requirements_ref": "direct-requirements-v1",
        "components": {"gateway": {"config_schema_version": 2, "settings": {
            "instance_id": "gateway-a", "bind_ports": ["service.direct_write", "service.account_read"],
            "options": {"role": "trading_owner", "dispatch_enabled": True, "cancel_enabled": True,
                        "control_enabled": True, "strategy_ledger_enabled": True,
                        "account_extensions_enabled": True, "delegation_enabled": True,
                        "parent_authority_enabled": True}}}},
        "communication": {"config_schema_version": 1, "profiles": {"server-transport": {
            "backend": "zmq", "config_schema_version": 1, "endpoints": {"rpc_bind": endpoint},
            "security_profile_ref": "security-a"}}}})


def _read_service(root, principals):
    from bt_api_gateway.account_read_model import GatewayAccountReadModel
    from bt_api_gateway.event_journal import GatewayEventJournal
    from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
    from bt_api_gateway.service_component import GatewayReadService, GatewayServiceAccountScope

    events = GatewayEventJournal(root / "account.sqlite")
    model = GatewayAccountReadModel(events,
        account_key=AccountKey("synthetic", "venue", "test", ACCOUNT), journal_account_scope=ACCOUNT,
        state_scope="state-a", required_coverage=(AccountResourceKey("future", "main"),),
        assert_current_generation=lambda _: None, max_staleness_seconds=30)
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    resource = AccountResourceKey("future", "main")
    model.start_generation("gen-1")
    model.finish_refresh(model.begin_refresh(), AccountObservation(
        account_key=model.account_key, observation_id="offline-observation", coverage=(resource,),
        balances=(AccountBalance(resource, "CNY", "100", "90", "10", now),), positions=(), valuation=None,
        started_at_utc=now, completed_at_utc=now, consistency="multi_query", balances_complete=True,
        positions_complete=True, open_orders=None, open_orders_complete=False))
    account = GatewayServiceAccountScope(account_ref=ACCOUNT, execution_domain_ref=DOMAIN,
        journal_account_scope=ACCOUNT, account_read_strategy_scope="state-a")
    return GatewayReadService(events, accounts={ACCOUNT: account},
        principals={item: GatewayPrincipal(item, frozenset({ACCOUNT}), frozenset({"state-a"}),
                                           frozenset({GatewayCommandKind.READ})) for item in principals},
        state_worker=model)


def _identity(client_order_id):
    return NativeOrderIdentity(ROUTE, client_order_id, {"trading_day": TRADING_DAY}, 1)


def _fact(client_order_id, kind):
    key = "native-" + client_order_id
    if kind == "trade":
        return GatewayReturnFact(ACCOUNT, ROUTE, INSTRUMENT, TRADING_DAY, DirectExecutionEventKind.TRADE,
            "synthetic-trade-" + client_order_id, identity=_identity(client_order_id),
            identity_keys=(key,), binding_keys=(key,), venue_key=key, trade_key=("venue", client_order_id),
            side="buy", offset="open", order_quantity="1", trade_quantity="1", trade_price="10",
            trade_time="09:00:00", schema_version=4, trade_date=TRADING_DAY)
    return GatewayReturnFact(ACCOUNT, ROUTE, INSTRUMENT, TRADING_DAY, DirectExecutionEventKind.ORDER,
        "synthetic-" + kind + "-" + client_order_id, identity=_identity(client_order_id),
        identity_keys=(key,), binding_keys=(key,), status=DirectOrderStatus(kind),
        filled_quantity="0" if kind in {"cancelled", "rejected"} else None)


def _gateway(root, endpoint, server_keys, publics, messages, controls):
    """The 63.13 loopback composition with a Risk delegate grant for one strategy."""
    owner = host = None
    try:
        from bt_api_gateway.direct_cancel_dispatch import GatewayDirectCancelDispatcher
        from bt_api_gateway.direct_cancel_journal import GatewayDirectCancelJournal
        from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
        from bt_api_gateway.direct_control import GatewayDirectControl
        from bt_api_gateway.direct_delegation import GatewayDelegateGrant
        from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher, NativeDispatchOutcome
        from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
        from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
        from bt_api_gateway.session_guard import LocalAccountSessionGuard
        from bt_api_py.gateway_account_comparison import GatewayAccountComparison
        from bt_api_py.gateway_account_observer import ACCOUNT_OBSERVER_OPERATIONS, GatewayAccountObserver
        from bt_api_py.gateway_delegate_actor_service import GatewayDelegateActorService
        from bt_api_py.gateway_delegation_service import GatewayDelegationService, GatewayDelegationSettings
        from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
        from bt_api_py.gateway_direct_service import (
            GatewayControlGrant,
            GatewayDirectGrant,
            GatewayDirectServiceBinding,
        )
        from bt_api_py.gateway_execution_stream_service import GatewayExecutionStreamService
        from bt_api_py.gateway_parent_service import OPERATIONS as PARENT_OPERATIONS
        from bt_api_py.gateway_parent_service import (
            GatewayParentGrant,
            GatewayParentService,
            GatewayParentSettings,
        )
        from bt_api_py.service_components import ComponentResources
        from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
        from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

        root = Path(root)
        (root / "guard").mkdir()
        holder = {}

        class ClaimPort:  # synthetic decision-B claim port (as in the Gateway tests)
            def ready(self):
                return True

            def claim_native(self, record, identity, validate):
                validate(0)
                return ("synthetic-claim", record.reservation_id)

            def native_check(self, claim):
                return lambda: True

            def retire(self, claim):
                return None

        def claiming(native):
            def wrapped(payload, port, scope):
                fences = []

                class Proxy:
                    def __getattr__(self, name):
                        return getattr(port, name)

                    def commit(self, record):
                        marker = port.commit(record)
                        if marker is not None:
                            fence = port.native_fence()
                            fence.__enter__()()
                            fences.append(fence)
                        return marker
                try:
                    return native(payload, Proxy(), scope)
                finally:
                    for fence in fences:
                        fence.__exit__(None, None, None)
            return wrapped

        def factory():
            guard = LocalAccountSessionGuard(root / "guard", ACCOUNT, "owner")
            journal = GatewayDirectCommandJournal.create(root / "journal.sqlite", ACCOUNT,
                                                         generation=guard.acquire())
            journal.enable_controls(guard)
            journal.enable_strategy_ledger(guard)
            journal.enable_account_extensions(guard)
            journal.enable_parent_authority(guard)
            holder["control"] = GatewayDirectControl(journal, guard)
            holder["ledger"] = GatewayDirectExecutionLedger(journal, guard)
            holder["parent"] = GatewayParentAuthority(journal, guard, now_ns=time.time_ns,
                trading_day=lambda: TRADING_DAY, transfer_completed=lambda _db, _spec: "0")

            def place(payload, port, account):
                identity = _identity(payload["client_order_id"])
                marker = port.commit(PreDispatchRecord(WriteOperation.PLACE, account, ROUTE, payload["symbol"],
                    identity, None, payload, TRADING_DAY, 1, "synthetic"))
                return NativeDispatchOutcome(True, identity, marker)

            dispatcher = GatewayDirectDispatcher(journal, ROUTE, guard, claiming(place),
                lambda identity: ("native-" + identity.client_order_id,), lambda _: True,
                claim_port=ClaimPort())

            def cancel(target, symbol, port, account):
                prepared = PreparedCancelRequest("cancel-" + target.client_order_id, target, symbol,
                    TRADING_DAY, 1, {"request_id": 12}, ("cancel-" + target.client_order_id,))
                marker = port.commit(PreDispatchRecord(WriteOperation.CANCEL, account, ROUTE, symbol, None,
                    target, {}, prepared.trading_day, prepared.session_generation, "synthetic", prepared))
                return NativeDispatchOutcome(True, target, marker)

            cancels = GatewayDirectCancelDispatcher(GatewayDirectCancelJournal(journal), dispatcher, guard,
                                                    ROUTE, cancel, lambda _: True)
            holder["journal"] = journal
            return GatewayDirectOwnerResources(dispatcher, journal, guard.release, cancel_dispatcher=cancels)

        owner = GatewayDirectOwner(factory, queue_size=8, max_queue_wait_seconds=5, busy_timeout_seconds=5)
        assert owner.start(10)
        journal, ledger, parent = holder["journal"], holder["ledger"], holder["parent"]
        stream = GatewayExecutionStreamService(ledger, journal, {STRATEGY.principal_ref: STRATEGY.actor_ref},
                                               execution_domain_ref=DOMAIN)
        binding = GatewayDirectServiceBinding(journal, {STRATEGY.principal_ref:
            GatewayDirectGrant(STRATEGY.actor_ref, frozenset({"rb"}))}, owner=owner, cancel_enabled=True,
            execution_stream=stream, execution_domain_ref=DOMAIN, control=holder["control"],
            control_grants={"operator": GatewayControlGrant("operator", True, frozenset(),
                                                           frozenset({"direct.control.status"}))})
        delegation = GatewayDelegationService(GatewayDelegationSettings(
            (GatewayDelegateGrant(RISK, ACCOUNT, STRATEGY.actor_ref, DOMAIN, "risk", "risk-v1",
                                  frozenset({INSTRUMENT}), LOGICAL),),
            lambda value: value == INSTRUMENT, parent_recheck=parent.recheck_child),
            owner=owner, journal=journal, instance_id="gateway-a", scope_ref="scope-a")
        # Parent authority as composed in 63.13; its Execution identity never connects here.
        execution = WireIdentity(WireRole.SERVICE, "execution-principal", "execution-service")
        parent_service = GatewayParentService(GatewayParentSettings((GatewayParentGrant(execution,
            ACCOUNT, STRATEGY.actor_ref, DOMAIN, "execution", "exec-v1", frozenset({INSTRUMENT}),
            PARENT_OPERATIONS),)), owner=owner, journal=journal, authority=parent,
            instance_id="gateway-a", scope_ref="scope-a")
        actor = GatewayDelegateActorService(delegation, release_target_recheck=parent.check_release_target,
            parent_cancel_recheck=parent.check_cancel_target, parent_grant_resolver=lambda *_: None)
        observers = frozenset({RISK.principal_ref})
        observer = GatewayAccountObserver(owner, journal, ledger, account_scope=ACCOUNT,
                                          execution_domain_ref=DOMAIN, principals=observers)
        comparison = GatewayAccountComparison(owner, journal, account_scope=ACCOUNT, principals=frozenset(),
                                              instruments=frozenset({INSTRUMENT}))
        read_service = _read_service(root, observers)
        template = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY.actor_ref)

        def direct(operations):
            return ResourceGrant("gateway-a", "service.direct_write", "scope-a", template, operations)
        observe = ResourceGrant("gateway-a", "service.account_read", "scope-a", ACCOUNT_ONLY,
                                ACCOUNT_OBSERVER_OPERATIONS)
        grants = {STRATEGY.principal_ref: (PrincipalGrant(STRATEGY, (direct(_strategy_ops()),)),),
                  RISK.principal_ref: (PrincipalGrant(RISK, (direct(_delegate_ops()), observe)),)}
        authority = TrustedServiceAuthority(identity=SERVICE, scope=WireScope(DOMAIN), scope_ref="scope-a",
            scope_version="scope-v1", security_ref="security-a", security_version="security-v1",
            registration_policy_ref="direct-policy-v1", registration_policy_version="direct-policy-v1",
            service_requirements_ref="direct-requirements-v1",
            service_requirements_version="direct-requirements-v1",
            curve_public_key=server_keys[0], curve_secret_key=server_keys[1], principals=publics,
            grants=grants)
        host = ServiceHost(_service_config(endpoint), authority, root / "registry.sqlite",
            lambda *_: ComponentResources.borrowed({"binding": binding, "delegation_service": delegation,
                "delegate_actor_service": actor, "parent_service": parent_service,
                "read_service": read_service, "account_observer": observer,
                "account_comparison": comparison}, ready=lambda: True))
        host.start()
        messages.put(("ready", os.getpid(), journal.journal_id))
        while True:
            try:
                item = controls.get_nowait()
            except queue.Empty:
                item = None
            if item == "stop":
                break
            if item is not None:
                client_order_id, kind = item
                fact = _fact(client_order_id, kind)
                result = owner.submit_service_call(lambda fact=fact: ledger.ingest(fact)).result(
                    timeout_seconds=5)
                messages.put(("ingested", client_order_id, kind, result.disposition))
            host.serve_once(10)
    except BaseException as error:
        messages.put(("error", type(error).__name__, str(error), traceback.format_exc()))
    finally:
        if host is not None and host.state == "started":
            host.close()
        if owner is not None:
            owner.close(5)
        messages.put(("closed", os.getpid()))


class MemoryDelegateHost:
    """Stand-in Risk storage; a real Risk service owns a durable store."""

    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        kind = name.split("_", 2)[-1]
        if name.startswith("save_delegate_"):
            def save(*args):
                key = args[0].command.request_key if kind == "intent" else (
                    args[0].operation_id if len(args) == 1 else args[0])
                self.values[(kind, key)] = args[-1]
                return args[-1]
            return save
        if name.startswith("load_delegate_"):
            return lambda key: self.values.get((kind, key))
        raise AttributeError(name)


class StandInRisk:
    """Answers risk.order.* by forwarding as the Risk delegate; keeps no policy."""

    def __init__(self, delegate):
        self.delegate, self.calls = delegate, []

    def call(self, mount, operation, arguments, **kwargs):
        from bt_api_py.gateway_order_contract import decode_gateway_order_request

        self.calls.append(operation)
        key = arguments["request_key"]
        view = hashlib.sha256(key.encode()).hexdigest()
        if operation == "risk.order.reserve":
            payload = dict(arguments["payload"])
            command = GatewayDelegatedCommand(ACCOUNT, STRATEGY.actor_ref, DOMAIN, RISK.principal_ref,
                RISK.actor_ref, "risk", RUN, key, gateway_payload_digest(payload), INSTRUMENT, "risk-v1")
            result = self.delegate.reserve(command, decode_gateway_order_request(payload, ACCOUNT))
            if result.outcome == "OBSERVED" and result.observation.state == "RESERVED":
                return RiskOrderResult(key, "RESERVED", state="RESERVED", permit_id="permit-" + key[-6:],
                    reservation_id=result.observation.reservation_id, view_digest=view).to_mapping()
            if result.outcome == "REQUEST_DENIED":
                return RiskOrderResult(key, "DENIED", state="DENIED", code="risk_gateway_refused",
                                       gateway_code=result.code).to_mapping()
            return RiskOrderResult(key, "UNKNOWN", state="UNKNOWN").to_mapping()
        if operation == "risk.order.dispatch":
            result = self.delegate.dispatch(key)
            if result.outcome == "QUEUED":
                return RiskOrderResult(key, "DISPATCHED", state="DISPATCHED",
                    permit_id=arguments["permit_id"], reservation_id=arguments["reservation_id"],
                    view_digest=arguments["view_digest"]).to_mapping()
            return RiskOrderResult(key, "UNKNOWN", state="UNKNOWN").to_mapping()
        raise AssertionError("stand-in Risk does not serve " + operation)


def _until(read, done, seconds=10.0):
    deadline = time.monotonic() + seconds
    while True:
        value = read()
        if done(value) or time.monotonic() >= deadline:
            return value
        time.sleep(0.02)


def _delegate_runtime(endpoint, server_public, keys):
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
    from bt_api_py.service_runtime_thread import ThreadedServiceClientRuntime

    raw = _service_config(_free_endpoint()).to_public_dict()
    raw["service_id"] = RISK.actor_ref
    raw["components"]["gateway"]["settings"]["bind_ports"] = ["service.direct_write"]
    raw["components"]["gateway"]["settings"]["options"] = {"role": "trading_owner"}
    raw["clients"] = {"gateway": {"config_schema_version": 1, "settings": {"bindings": [{
        "mount": "upstream.direct_write", "service_id": SERVICE.actor_ref, "instance_id": "gateway-a",
        "scope_ref": "scope-a", "account_ref": ACCOUNT, "transport_ref": "client-transport"}]}}}
    raw["communication"]["profiles"]["client-transport"] = {"backend": "zmq", "config_schema_version": 1,
        "endpoints": {"rpc_connect": endpoint}, "security_profile_ref": "security-a"}
    config = parse_service_config(raw)
    curve = {"security-a": ClientCurveKeys(server_public, *keys)}
    return ThreadedServiceClientRuntime(lambda: ServiceClientRuntime(config, identity=RISK,
        scope_resolver=lambda _: SCOPE, peer_resolver=lambda _: SERVICE,
        transport_factory=ZmqTransportFactory(curve), run_id=RUN,
        requested_operations={"upstream.direct_write": _delegate_ops()}))


def _strategy_api(endpoint, server_public, keys, host, standin, monkeypatch):
    from bt_api_py.gateway_api import GatewayBtApi
    from bt_api_py.gateway_direct_client import GatewayClientRoute
    from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
    from bt_api_py.risk_service_client import RiskClientRoute, RiskServiceClient
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import ClientCurveKeys
    from bt_api_py.service_runtime_thread import (
        BindingSnapshot,
        RuntimeSnapshot,
        ThreadedServiceClientRuntime,
    )

    config = parse_client_config({"client_config_schema_version": 1, "process_role": "strategy_client",
        "registration": {"strategy_ref": STRATEGY.actor_ref},
        "clients": {"gateway": {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": "broker.direct_write", "service_id": SERVICE.actor_ref, "instance_id": "gateway-a",
            "scope_ref": "scope-a", "account_ref": ACCOUNT, "transport_ref": "client-transport"}],
            "options": {"request_timeout_ms": 2000}}}},
        "communication": {"config_schema_version": 1, "profiles": {"client-transport": {
            "backend": "zmq", "config_schema_version": 1, "endpoints": {"rpc_connect": endpoint},
            "security_profile_ref": "security-a"}}}})
    route = GatewayClientRoute("broker.direct_write", SERVICE.actor_ref, "gateway-a", "scope-a", SCOPE, STRATEGY)
    session = GatewayStrategyClientSession(config, binding=host._binding, route=route, peer=SERVICE,
        security_profiles={"security-a": ClientCurveKeys(server_public, *keys)}, host=host,
        delegated_cancel_host=host, requested_operations=_strategy_ops())
    risk_route = RiskClientRoute("broker.risk_order", "risk", "risk-a", "risk-scope", SCOPE, STRATEGY)
    risk = RiskServiceClient(
        ThreadedServiceClientRuntime(lambda: None, require_unregister_ack=True), route=risk_route
    )
    snapshot = RuntimeSnapshot("running", True, True, None, (BindingSnapshot(
        "risk-registration", "risk-epoch", True, risk_route.mount, risk_route.service_id,
        risk_route.instance_id, risk_route.scope_ref, SCOPE,
        frozenset({"risk.order.reserve", "risk.order.dispatch", "risk.order.release",
                   "risk.order.status"}), True),), 0, 0, STRATEGY, RUN,
        strict_unregister_ack=True)
    # Simulated strict-policy status: Risk answers in this process rather than a
    # Risk host; this snapshot is not a Registry or unregister acknowledgement.
    monkeypatch.setattr(risk._runtime, "status", lambda: snapshot)
    monkeypatch.setattr(risk._runtime, "start", lambda **kw: snapshot)
    monkeypatch.setattr(risk._runtime, "close", lambda **kw: snapshot)
    monkeypatch.setattr(risk._runtime, "call", standin.call)
    return GatewayBtApi(session, exchange_name=ROUTE, owns_session=True, risk_client=risk)


def _deliver(broker, strategy):
    while True:
        notice = broker.get_notification()
        if notice is None:
            return
        strategy._addnotification(notice)
        strategy._notify()
        strategy.clear()


def test_order_placed_through_risk_is_dispatched_filled_and_cancelled_through_the_delegate(
        tmp_path, monkeypatch):
    import backtrader.brokers._btapi_gateway_stream as stream_module
    from bt_api_py.gateway_delegate_service_client import GatewayDelegateRoute, GatewayDelegateServiceClient
    from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy

    from backtrader.live_state import StrategyStateDir
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order, framework

    monkeypatch.setattr(stream_module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)
    context = multiprocessing.get_context("spawn")
    messages, controls = context.Queue(), context.Queue()
    keys = {name: zmq.curve_keypair() for name in ("server", "strategy", "risk")}
    publics = {keys["strategy"][0]: STRATEGY.principal_ref, keys["risk"][0]: RISK.principal_ref}
    endpoint = _free_endpoint()
    process = context.Process(target=_gateway, args=(str(tmp_path), endpoint, keys["server"], publics,
                                                     messages, controls))
    process.start()
    api = delegate_runtime = None
    try:
        ready = messages.get(timeout=60)
        assert ready[0] == "ready", "\n".join(map(str, ready))
        server_public = keys["server"][0]
        # Strategy state at pending v7.
        path = tmp_path / "strategy"
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(ready[2], ACCOUNT, STRATEGY.actor_ref, STRATEGY.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref=STRATEGY.principal_ref,
            actor_ref=STRATEGY.actor_ref, execution_domain_ref=DOMAIN, account_scope=ACCOUNT,
            strategy_scope=STRATEGY.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        # The strategy's run must be live before the delegate can register for it.
        standin = StandInRisk(None)
        api = _strategy_api(endpoint, server_public, keys["strategy"], host, standin, monkeypatch)
        assert api.start(timeout_seconds=10).healthy
        delegate_runtime = _delegate_runtime(endpoint, server_public, keys["risk"])
        assert delegate_runtime.start(timeout_seconds=10).healthy
        standin.delegate = GatewayDelegateServiceClient(delegate_runtime, route=GatewayDelegateRoute(
            "upstream.direct_write", SERVICE.actor_ref, "gateway-a", "scope-a", SCOPE, RISK),
            host=MemoryDelegateHost())
        data, broker, strategy = framework()
        broker.store.contract_metadata = {"rb": {"instrument_key": INSTRUMENT.to_dict(),
            "exchange_name": ROUTE, "quantity_unit": "lots", "time_in_force": "GFD"}}
        monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: {
            "key": {"source_ref": "s", "entitlement_ref": "e", "instrument": INSTRUMENT.to_dict(),
                    "channel": "tick", "depth": None, "timeframe": None},
            "epoch": "e1", "sequence": 1, "message_id": "m1"})
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy(ROUTE, "UTC"), timeout_seconds=5,
            sequence=state.sequence)

        # PLACE through Risk: reserve and dispatch forwarded by the delegate.
        order = _limit_order(strategy, data)
        broker.submit(order)
        key = order.info.gateway_request_key
        assert standin.calls == ["risk.order.reserve", "risk.order.dispatch"]
        record = host.load_delegated_command(key)
        assert record.actor_principal == RISK.principal_ref and record.dispatch_requested is True
        assert host.load_record(key) is None  # never this strategy's own command
        _deliver(broker, strategy)
        sent = _until(lambda: api.delegated_command_status(ROUTE, key),
                      lambda r: r.observation is not None and r.observation.state == "SENT")
        assert sent.observation.state == "SENT" and sent.observation.actor_principal == RISK.principal_ref

        # A synthetic venue fill of the delegate's order reaches this BT order.
        controls.put((key, "trade"))
        assert messages.get(timeout=10) == ("ingested", key, "trade", "ATTRIBUTED")
        _until(lambda: (broker.next(), order.executed.size)[1], lambda size: size == 1)
        assert order.status == order.Completed and broker.positions["rb"].size == 1
        _deliver(broker, strategy)
        assert [e[0] for e in strategy.events][-2:] == ["order", "trade"]
        assert host.load_execution_checkpoint().applied_sequence >= 1  # consumed, not skipped

        # A second order is cancelled through the strategy's delegated cancel (Risk not involved).
        second = _limit_order(strategy, data, price=9)
        broker.submit(second)
        second_key = second.info.gateway_request_key
        _deliver(broker, strategy)
        _until(lambda: api.delegated_command_status(ROUTE, second_key),
               lambda r: r.observation is not None and r.observation.state == "SENT")
        before = list(standin.calls)
        broker._gateway_cancel_order(second)
        assert standin.calls == before  # cancel never goes through Risk
        operation_id = "cancel-" + hashlib.sha256(second_key.encode()).hexdigest()
        plan = host.load_delegated_cancel_plan(operation_id)
        assert plan.target_actor_principal == RISK.principal_ref and plan.request_key == second_key
        cancel = _until(lambda: api.delegated_cancel_status(ROUTE, operation_id),
                        lambda r: r.observation is not None and r.observation.state == "SENT")
        assert cancel.observation.state == "SENT"
        assert host.load_delegated_cancel_observation(operation_id).state == "SENT"
        controls.put((second_key, "cancelled"))
        assert messages.get(timeout=10) == ("ingested", second_key, "cancelled", "ATTRIBUTED")
        _until(lambda: (broker.next(), second.status)[1], lambda status: status == second.Canceled)
        assert second.status == second.Canceled and second.executed.size == 0
        assert broker.positions["rb"].size == 1
    finally:
        if api is not None:
            api.close(timeout_seconds=10)
        if delegate_runtime is not None:
            delegate_runtime.close(timeout_seconds=10)
        controls.put("stop")
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
