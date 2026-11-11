"""Iteration 64: lifecycle of a Backtrader order placed through the Risk service.

UNIT/FAKE: real BT broker, real pending host (state v7) and real SDK facade; Risk and
Gateway replies are synthetic. Nothing here is account or venue evidence.
"""
from dataclasses import replace

import pytest
from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionStreamProgress
from bt_api_base.risk_service_protocol import RiskOrderResult
from bt_api_py.gateway_api import GatewayBtApi, GatewayRiskPermitRecord, GatewayRiskRoutedResult
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext,
    GatewayExecutionStreamClientResult,
)
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.gateway_strategy_delegated import (
    GatewayDelegatedCommandObservation,
    GatewayDelegatedCommandResult,
)
from bt_api_py.risk_service_client import RiskCallResult, RiskClientRoute, RiskServiceClient
from bt_api_py.service_runtime_thread import (
    BindingSnapshot,
    RuntimeSnapshot,
    ThreadedServiceClientRuntime,
)

from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    INSTRUMENT,
    SYNTHETIC_MARKET_REF,
    _limit_order,
    deliver,
    framework,
)
from tests.unit.brokers.test_iter64_gateway_risk_projection import _risk_api
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import page
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated
from tests.unit.live_state.test_iter64_gateway_delegated_state import delegated_event

RISK = "risk-principal"
ROUTE = "CTP___FUTURE"


@pytest.fixture(autouse=True)
def _every_step_runs(monkeypatch):
    # As in the iteration 63 consumer tests: no idle pause between test steps.
    import backtrader.brokers._btapi_gateway_stream as module

    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)


class Venue:
    """Synthetic Risk/Gateway replies seen by the facade; records every call."""

    def __init__(self, host):
        self.host, self.calls, self.events, self.acks = host, [], [], []
        self.state, self.version, self.actor = "RESERVED", 1, RISK
        self.reserve = "RESERVED"
        self.dispatch = "DISPATCHED"
        self.delegated_available = True

    def observation(self, key):
        intent = self.host.load_intent(key)
        return GatewayDelegatedCommandObservation("account-a", "strategy-a", self.actor, key,
            "res-r", intent.digest, self.state, self.version, "g1", "g1")


def install(api, venue, monkeypatch, binding, consumer):
    def reserve(route, request, **kw):
        venue.calls.append("reserve")
        key = request.idempotency_key
        if venue.reserve == "RESERVED":
            return GatewayRiskRoutedResult("OBSERVED", record=GatewayRiskPermitRecord(
                key, "RESERVED", "permit-1", "res-r", "d" * 64, None))
        return GatewayRiskRoutedResult("UNKNOWN", code="RISK_OUTCOME_UNKNOWN")

    def dispatch(route, key, *, market_ref=None, timeout_seconds):
        venue.calls.append(("dispatch", market_ref))
        assert venue.host.load_delegated_command(key).dispatch_requested is True  # durable first
        if venue.dispatch == "DISPATCHED":
            venue.state, venue.version = "SENT", 3
            return GatewayRiskRoutedResult("QUEUED", record=GatewayRiskPermitRecord(
                key, "DISPATCHED", "permit-1", "res-r", "d" * 64, None))
        if venue.dispatch == "DENIED":
            return GatewayRiskRoutedResult("REQUEST_DENIED", code="RISK_PRICE_BAND_EXCEEDED",
                risk_code="risk_price_band_exceeded", risk_denied="risk_price_band_exceeded")
        return GatewayRiskRoutedResult("UNKNOWN", code="RISK_OUTCOME_UNKNOWN")

    def delegated_status(route, key, *, timeout_seconds):
        venue.calls.append("delegated_status")
        if not venue.delegated_available:
            return GatewayDelegatedCommandResult("UNAVAILABLE", code="DELEGATED_COMMAND_UNAVAILABLE")
        return GatewayDelegatedCommandResult("OBSERVED", venue.observation(key))

    def release(route, key, *, operation_id, timeout_seconds):
        venue.calls.append("release")
        venue.state, venue.version = "RELEASED", 2
        return GatewayRiskRoutedResult("OBSERVED", record=GatewayRiskPermitRecord(
            key, "RELEASED", "permit-1", "res-r", None, None))

    monkeypatch.setattr(api, "reserve_order", reserve)
    monkeypatch.setattr(api, "dispatch_order", dispatch)
    monkeypatch.setattr(api, "delegated_command_status", delegated_status)
    monkeypatch.setattr(api, "release_order", release)
    monkeypatch.setattr(api, "command_status", lambda *a, **kw: pytest.fail("own command_status"))
    monkeypatch.setattr(api, "cancel_order", lambda *a, **kw: pytest.fail("cancel_order"))
    stream = api.gateway_execution_stream(ROUTE)

    def read(after, epoch, limit, *, timeout_seconds):
        selected = [event for event in venue.events if event.sequence > after][:limit]
        return GatewayExecutionStreamClientResult("OBSERVED", page=page(binding, consumer, selected),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))

    def ack(sequence, expected_epoch, *, timeout_seconds):
        venue.acks.append(sequence)
        return GatewayExecutionStreamClientResult("OBSERVED", progress=GatewayExecutionStreamProgress(
            binding, consumer, expected_epoch, 10, sequence))

    monkeypatch.setattr(stream, "read_after", read)
    monkeypatch.setattr(stream, "ack", ack)


def bound(state, ready, inputs, monkeypatch, api=None):
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    _, binding, consumer = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()  # the fixture's key-a owns local sequence 1
    api = api or _risk_api(host, inputs[1])
    venue = Venue(host)
    install(api, venue, monkeypatch, binding, consumer)
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    return host, api, venue, data, broker, strategy


def rebind(state, host, api, monkeypatch):
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
        orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy(ROUTE, "UTC"), sequence=state.sequence)
    return data, broker, strategy


def fill(host, key, *, seq=5, principal=RISK, reservation="res-r", fact="a" * 64):
    event = replace(delegated_event(host, key=key, principal=principal, reservation=reservation, seq=seq,
                                    fact=fact), request_key=key)
    return dated(event, seq, date="20261107", metadata=False, fact=fact, offset="open",
                 order_quantity="1", filled_quantity="1", remaining_quantity="0", trade_quantity="1")


def submit(broker, strategy, data):
    order = _limit_order(strategy, data)
    broker.submit(order)
    deliver(broker, strategy)  # the local "submitted" notice
    return order, order.info.gateway_request_key


# --- PLACE: PREPARED then dispatch through Risk -------------------------------------------


def test_reserved_through_risk_is_prepared_durably_then_dispatched(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    assert venue.calls == ["reserve", "delegated_status", ("dispatch", SYNTHETIC_MARKET_REF),
                           "delegated_status"]
    record = host.load_delegated_command(key)
    assert (record.permit_id, record.reservation_id, record.view_digest) == ("permit-1", "res-r", "d" * 64)
    assert record.actor_principal == RISK and record.dispatch_requested is True
    assert (record.gateway_state, record.gateway_version) == ("SENT", 3)
    assert order.status == order.Submitted and order.info.gateway_risk_routed is True
    assert key in broker._gateway_stream_binding.dispatched
    assert host.load_record(key) is None  # never an own Gateway command


def test_a_fill_of_a_risk_placed_order_reaches_order_position_and_strategy(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    venue.events.append(fill(host, key))
    broker.next()
    assert order.status == order.Completed and order.executed.size == 1
    assert broker.positions["rb"].size == 1
    deliver(broker, strategy)
    assert [event[0] for event in strategy.events][-2:] == ["order", "trade"]
    broker.next()
    assert venue.acks == [5] and host.load_execution_checkpoint().acknowledged_sequence == 5


@pytest.mark.parametrize("status,expected", [("CANCELLED", "Canceled"), ("REJECTED", "Rejected")])
def test_terminal_order_states_of_a_risk_placed_order_are_applied(state, ready, inputs, monkeypatch,
                                                                  status, expected):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    source = fill(host, key)
    obs = replace(source.observation, kind=DirectExecutionEventKind.ORDER, status=DirectOrderStatus[status],
                  trade_key_digest=None, trade_quantity=None, trade_price=None, trade_time=None,
                  trade_date=None, filled_quantity="0", remaining_quantity="1", schema_version=1,
                  trade_metadata_only=False, offset=None)
    venue.events.append(replace(source, observation=obs))
    broker.next()
    assert order.status == getattr(order, expected) and order.executed.size == 0
    deliver(broker, strategy)
    assert strategy.events[-1][0] == "order"


@pytest.mark.parametrize("case", ["wrong_principal", "strategy_principal", "wrong_reservation"])
def test_a_return_that_does_not_match_the_recorded_delegate_never_binds(state, ready, inputs, monkeypatch,
                                                                        case):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    kwargs = {"wrong_principal": {"principal": "another-principal"},
              "strategy_principal": {"principal": "principal-a"},
              "wrong_reservation": {"reservation": "res-other"}}[case]
    venue.events.append(fill(host, key, **kwargs))
    with pytest.raises(Exception):
        broker.next()
    assert order.status == order.Submitted and order.executed.size == 0
    assert host.read_execution_events(limit=8) == () and venue.acks == []


def test_a_return_of_an_unknown_key_never_binds(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    venue.events.append(fill(host, "not-this-strategys-key"))
    with pytest.raises(Exception):
        broker.next()
    assert order.executed.size == 0 and host.read_execution_events(limit=8) == ()


def test_a_later_different_delegate_principal_is_refused(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    venue.actor = "another-principal"
    assert broker._gateway_risk_learn(broker._gateway_stream_binding, key) is None
    assert broker._gateway_stream_binding.state == "RISK_BINDING_CONFLICT"
    assert host.load_delegated_command(key).actor_principal == RISK


# --- unknown outcomes keep the order pending and block (D63-04) ----------------------------


def test_unknown_risk_dispatch_keeps_the_order_and_blocks_new_orders(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    assert order.status == order.Submitted
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))
    assert venue.calls.count("reserve") == 1


def test_risk_dispatch_refusal_withdraws_the_reservation(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "DENIED"
    order, key = submit(broker, strategy, data)
    assert "release" in venue.calls
    assert order.status == order.Canceled and order.info.risk_denied == "risk_price_band_exceeded"
    assert host.load_delegated_command(key).gateway_state == "RELEASED"
    assert broker.gateway_risk_summary()["refusals"] == {"risk_price_band_exceeded": 1}


# --- restart recovery --------------------------------------------------------------------


def unknown_reserve_then_restart(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.reserve = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    assert host.load_delegated_command(key) is None and order.status == order.Submitted
    venue.calls.clear()
    data2, broker2, strategy2 = rebind(state, host, api, monkeypatch)
    restored = next(o for o in broker2.orders.values() if o.info.get("gateway_request_key") == key)
    return host, api, venue, data2, broker2, strategy2, restored, key


def test_restart_resolves_a_held_reservation_and_withdraws_it(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "RESERVED", state="RESERVED", permit_id="permit-1",
                                    reservation_id="res-r", view_digest="d" * 64)))
    broker.next()  # recover: the Gateway holds the delegated command
    record = host.load_delegated_command(key)
    assert (record.actor_principal, record.permit_id, record.dispatch_requested) == (RISK, "permit-1", False)
    broker.next()  # never asked to dispatch: withdrawn through Risk, never resent
    assert "release" in venue.calls and not any(c[0] == "dispatch" for c in venue.calls
                                                 if isinstance(c, tuple))
    assert order.status == order.Canceled


def test_restart_ends_a_definite_risk_refusal(state, ready, inputs, monkeypatch):
    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch)
    venue.delegated_available = False
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "DENIED", state="DENIED", code="risk_order_count_limit")))
    broker.next()
    assert order.status == order.Rejected and order.info.risk_denied == "risk_order_count_limit"
    assert host.local_order_notifications()["reject:" + key]["code"] == "RISK_ORDER_COUNT_LIMIT"


@pytest.mark.parametrize("risk_reply", ["not_found", "unavailable"])
def test_restart_keeps_an_unprovable_outcome_unknown_and_blocking(state, ready, inputs, monkeypatch,
                                                                  risk_reply):
    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch)
    venue.delegated_available = False
    reply = (RiskCallResult("ANSWERED", RiskOrderResult(key, "NOT_FOUND")) if risk_reply == "not_found"
             else RiskCallResult("NOT_SENT", code="ROUTE_UNAVAILABLE"))
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: reply)
    for _ in range(3):
        broker.next()
    assert order.status == order.Submitted and host.load_delegated_command(key) is None
    assert "reject:" + key not in host.local_order_notifications()
    assert not any(isinstance(c, tuple) and c[0] == "dispatch" for c in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


# --- cancel through the strategy's delegated Gateway operations -----------------------------


def test_cancel_uses_a_durable_delegated_cancel_even_with_risk_down(state, ready, inputs, monkeypatch):
    """Real SDK delegated client and real BT pending host as its cancel host."""
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    _, binding, consumer = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    host.upgrade_for_local_notifications()
    host.upgrade_for_risk_routing()
    state.sequence.allocate()
    route = inputs[1]
    ops = frozenset({"direct.events.read_after", "direct.events.ack", "direct.delegated_command_status",
                     "direct.delegated_cancel", "direct.delegated_cancel_status"})
    session = GatewayStrategyClientSession(_config(route), binding=host._binding, route=route,
        peer=_peer(route), security_profiles=_keys(), host=host, delegated_cancel_host=host,
        requested_operations=ops)
    risk = RiskServiceClient(ThreadedServiceClientRuntime(lambda: None), route=RiskClientRoute(
        "broker.risk_order", "risk", "risk-a", "risk-scope", route.scope, route.identity))
    monkeypatch.setattr(risk._runtime, "call", lambda *a, **kw: pytest.fail("Risk called for a cancel"))
    api = GatewayBtApi(session, exchange_name=ROUTE, risk_client=risk)
    venue = Venue(host)
    install(api, venue, monkeypatch, binding, consumer)
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    order, key = submit(broker, strategy, data)
    # The real facade cancel path: delegated status + delegated cancel over the session.
    monkeypatch.undo()  # drop the facade stubs; keep the stream stubs below
    install_stream_only(api, venue, monkeypatch, binding, consumer)
    monkeypatch.setattr(risk._runtime, "call", lambda *a, **kw: pytest.fail("Risk called for a cancel"))
    snapshot = _snapshot(route, ops)
    monkeypatch.setattr(session.runtime, "status", lambda: snapshot)
    gateway_calls = []

    def call(mount, operation, arguments, **kwargs):
        gateway_calls.append(operation)
        intent = host.load_intent(key)
        if operation == "direct.delegated_command_status":
            return {"status": "OBSERVED", "schema_version": 1, "account_scope": "account-a",
                    "strategy_scope": "strategy-a", "actor_principal": RISK, "request_key": key,
                    "reservation_id": "res-r", "digest": intent.digest, "state": "SENT", "version": 3,
                    "owner_generation": "g1", "reservation_generation": "g1"}
        assert operation == "direct.delegated_cancel", operation
        return {"status": "OK", "cancel_queue_state": "QUEUED", "record": {
            "account_scope": "account-a", "strategy_scope": "strategy-a",
            "requester_principal": "principal-a", "target_actor_principal": RISK,
            "request_key": key, "operation_id": arguments["operation_id"], "attempt_id": "attempt-1",
            "target_reservation_id": "res-r", "target_digest": intent.digest, "state": "REQUESTED",
            "version": 1, "owner_generation": "g1", "attempt_generation": "g1"}}

    monkeypatch.setattr(session.runtime, "call", call)
    broker._gateway_cancel_order(order)
    assert gateway_calls == ["direct.delegated_command_status", "direct.delegated_command_status",
                             "direct.delegated_cancel"]
    assert "direct.cancel" not in gateway_calls
    operation_id = next(iter(host._store._load()["gateway"]["delegated_cancel_attempts"]))
    assert host.load_delegated_cancel_plan(operation_id).target_actor_principal == RISK
    assert host.load_delegated_cancel_observation(operation_id).state == "REQUESTED"
    assert broker._gateway_stream_binding.state != "CANCEL_UNKNOWN"


def install_stream_only(api, venue, monkeypatch, binding, consumer):
    stream = api.gateway_execution_stream(ROUTE)
    monkeypatch.setattr(stream, "read_after", lambda *a, **kw: GatewayExecutionStreamClientResult(
        "UNKNOWN", code="RPC_OUTCOME_UNKNOWN"))


def _config(route):
    from bt_api_py.service_config import parse_client_config

    return parse_client_config({"client_config_schema_version": 1, "process_role": "strategy_client",
        "registration": {"strategy_ref": route.scope.strategy_ref},
        "clients": {"gateway": {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": route.mount, "service_id": route.service_id, "instance_id": route.instance_id,
            "scope_ref": route.scope_ref, "account_ref": route.scope.account_ref,
            "transport_ref": "transport"}]}}},
        "communication": {"config_schema_version": 1, "profiles": {"transport": {
            "backend": "zmq", "config_schema_version": 1,
            "endpoints": {"rpc_connect": "tcp://127.0.0.1:12345"}, "security_profile_ref": "security"}}}})


def _peer(route):
    from bt_api_base.service_protocol import WireIdentity, WireRole

    return WireIdentity(WireRole.SERVICE, "service", route.service_id)


def _keys():
    from bt_api_py.service_runtime import ClientCurveKeys

    return {"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)}


def _snapshot(route, ops):
    binding = BindingSnapshot("registration", "epoch", True, route.mount, route.service_id,
                              route.instance_id, route.scope_ref, route.scope, ops, True)
    return RuntimeSnapshot("running", True, True, None, (binding,), 0, 0, route.identity, route.scope.run_id)


@pytest.mark.parametrize("case", ["wrong_principal", "strategy_principal", "wrong_reservation", "match"])
def test_the_consumer_rechecks_the_delegated_binding_itself(state, ready, inputs, monkeypatch, case):
    """Defence in depth: the broker re-checks a stored return before applying it."""
    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    order, key = submit(broker, strategy, data)
    kwargs = {"wrong_principal": {"principal": "another-principal"},
              "strategy_principal": {"principal": "principal-a"},
              "wrong_reservation": {"reservation": "res-other"}, "match": {}}[case]
    event = fill(host, key, **kwargs)
    binding = broker._gateway_stream_binding
    if case == "match":
        assert broker._gateway_stream_event_binding(binding, event, order).symbol == "rb"
        return
    with pytest.raises(GatewayExecutionStreamError, match="EVENT_BINDING"):
        broker._gateway_stream_event_binding(binding, event, order)
