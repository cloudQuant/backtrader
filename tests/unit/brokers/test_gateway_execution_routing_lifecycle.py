"""Broker routing uses durable local state; all services here are synthetic."""
import sqlite3

import backtrader as bt
import pytest

from bt_api_py.execution_routing import (
    ExecutionOrderRouter, ExecutionPreparedRoute, ExecutionRoutingOutcome,
    ExecutionRoutingResult, install_execution_routing_tables, parse_execution_routing,
)
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_direct_client import GatewayClientResult
from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    INSTRUMENT, _bound_submit_fixture, deliver, inputs, ready, state, strategy_dir,  # noqa: F401
)
from tests.unit.live_state.test_gateway_execution_route_binding import CONFIG


def setup_route(state, ready, inputs, monkeypatch, *, matched):
    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    host.upgrade_for_risk_routing().upgrade_for_execution_routing()
    plain = CONFIG.to_plain()
    plain['instruments'] = [INSTRUMENT.to_dict()]
    plain['rules'][0]['match']['instrument'] = INSTRUMENT.to_dict()
    plain['rules'][0]['match']['side'] = 'buy' if matched else 'sell'
    config = parse_execution_routing(plain)
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.execute('BEGIN IMMEDIATE')
    install_execution_routing_tables(db)
    db.commit()
    calls = []
    class Port:
        def submit(self, payload):
            key = next(iter(host.iter_order_snapshots()))
            assert host.load_execution_route(key).kind == 'EXECUTION_PARENT'
            assert host.local_order_notifications()[key]['status'] == 'pending'
            calls.append(('parent', payload))
    router = ExecutionOrderRouter(db=db, config=config, execution_port=Port(),
                                  risk_selected=False, clock=lambda: 1)
    monkeypatch.setattr(GatewayBtApi, 'execution_selected', property(lambda _: True))
    monkeypatch.setattr(GatewayBtApi, 'execution_configuration_id', property(lambda _: config.configuration_id))
    monkeypatch.setattr(api, 'route_execution_order', lambda route, intent, *, before_submit:
                        router.route(intent, before_submit=before_submit))
    monkeypatch.setattr(api, 'execution_order_status', lambda route, intent: router.status(intent))
    monkeypatch.setattr(api, 'cancel_execution_order', lambda route, intent: router.cancel(intent))
    monkeypatch.setattr(api, 'reserve_order', lambda *a, **k: calls.append(('reserve', a[1])) or GatewayClientResult('UNKNOWN'))
    monkeypatch.setattr(api, 'command_status', lambda *a, **k: pytest.fail('Gateway status for parent'))
    monkeypatch.setattr(api, 'cancel_order', lambda *a, **k: pytest.fail('Gateway cancel for parent'))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    return host, api, data, broker, strategy, order, calls, router


def test_matching_parent_is_saved_before_one_submit_and_never_falls_back(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert host.load_execution_route(key).kind == 'EXECUTION_PARENT'
    assert [call[0] for call in calls] == ['parent']
    assert order.status == order.Submitted
    deliver(broker, strategy)
    broker.cancel(order)
    assert order.status == order.Submitted
    broker.p.stop_cancel_timeout = 0
    summary = broker._gateway_stop_working_orders()
    assert summary['unresolved_working_orders'] == 1
    assert summary['cancel_requested'] == 0
    assert summary['cancel_attempted_unknown'] == 1
    assert summary['awaiting_confirmation'] == 1
    assert summary['refused'] == {}
    assert [call[0] for call in calls] == ['parent']
    db_result = router.route(host.load_intent(key))
    assert db_result.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
    assert [call[0] for call in calls] == ['parent']


def test_no_match_requires_fresh_proof_before_single_gateway_reserve(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=False)
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert host.load_execution_route(key).kind == 'GATEWAY'
    assert [call[0] for call in calls] == ['reserve']
    assert router.route(host.load_intent(key)).direct_decision is None


@pytest.mark.parametrize('outcome', [ExecutionRoutingOutcome.EXECUTION_UNKNOWN,
                                    ExecutionRoutingOutcome.EXECUTION_UNAVAILABLE,
                                    ExecutionRoutingOutcome.EXECUTION_REJECTED])
def test_failed_execution_never_routes_to_gateway(state, ready, inputs, monkeypatch, outcome):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    monkeypatch.setattr(api, 'route_execution_order', lambda *a, **k: ExecutionRoutingResult(outcome))
    broker.submit(order)
    assert host.load_execution_route(order.info['gateway_request_key']).kind == 'PENDING'
    assert order.status == order.Submitted and not calls
    broker.cancel(order)
    assert order.status == order.Submitted and not calls


def test_source_bound_local_receipt_stays_submitted(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    def route(_route, intent, *, before_submit):
        prepared = ExecutionPreparedRoute(intent.binding.account_scope, intent.binding.strategy_scope,
            intent.request_key, intent.digest, 'req', 'a' * 64,
            api.execution_configuration_id, intent.route.scope.execution_domain_ref, 'parent')
        assert before_submit(prepared)
        return ExecutionRoutingResult(ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT,
                                      request_id='req', request_sha256='a' * 64, parent_ref='parent')
    monkeypatch.setattr(api, 'route_execution_order', route)
    broker.submit(order)
    assert order.status == order.Submitted and order.executed.size == 0
    assert host.load_execution_route(order.info['gateway_request_key']).kind == 'EXECUTION_PARENT'
    assert not calls


@pytest.mark.parametrize('matched', [False, True])
def test_restart_parent_and_pending_never_resubmit_or_reject_not_found(state, ready, inputs, monkeypatch, matched):
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _rebind
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    if not matched:
        monkeypatch.setattr(api, 'route_execution_order', lambda *a, **k:
                            ExecutionRoutingResult(ExecutionRoutingOutcome.EXECUTION_UNKNOWN))
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert host.load_execution_route(key).kind == ('EXECUTION_PARENT' if matched else 'PENDING')
    deliver(broker, strategy)
    _, restored, new_strategy = _rebind(state, host, api, monkeypatch)
    recovered = restored._gateway_binding(new_strategy, required=True).orders[key]
    restored.cancel(recovered)
    from bt_api_py.gateway_execution_stream_client import GatewayExecutionReadContext, GatewayExecutionStreamClientResult
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import page
    _, binding, consumer = ready
    stream = restored._gateway_stream_binding.stream
    def read(after, epoch, limit, *, timeout_seconds):
        return GatewayExecutionStreamClientResult('OBSERVED', page=page(binding, consumer, []),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))
    monkeypatch.setattr(stream, 'read_after', read)
    restored.next()
    assert restored.gateway_execution_stream_status() == 'EXECUTION_RECOVERY_PENDING'
    assert recovered.status == recovered.Submitted and recovered.executed.size == 0
    assert 'reject:' + key not in host.local_order_notifications()
    assert [c[0] for c in calls] == (['parent'] if matched else [])


def test_parent_key_gateway_event_is_not_ingested_or_projected(state, ready, inputs, monkeypatch):
    from dataclasses import replace
    from bt_api_py.gateway_execution_stream_client import GatewayExecutionReadContext, GatewayExecutionStreamClientResult
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import event_for, page
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    broker.submit(order)
    key = order.info['gateway_request_key']
    deliver(broker, strategy)
    event = replace(event_for(host), request_key=key)
    _, binding, consumer = ready
    stream = broker._gateway_stream_binding.stream
    def read(after, epoch, limit, *, timeout_seconds):
        return GatewayExecutionStreamClientResult('OBSERVED', page=page(binding, consumer, [event]),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))
    monkeypatch.setattr(stream, 'read_after', read)
    before = host.load_execution_checkpoint()
    broker.next()
    assert broker.gateway_execution_stream_status() == 'EXECUTION_EVENT_UNBOUND'
    assert host.load_execution_checkpoint() == before and order.executed.size == 0
    assert [c[0] for c in calls] == ['parent']


def test_no_match_risk_consumes_first_save_ticket_once(state, ready, inputs, monkeypatch):
    from types import MethodType
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=False)
    monkeypatch.setattr(GatewayBtApi, 'risk_selected', property(lambda _: True))
    router._risk_selected = True
    tickets = []
    def reserve(self, route, request, *, timeout_seconds, first_send_ticket):
        key = request.idempotency_key
        assert host.load_execution_route(key).kind == 'RISK'
        assert host.consume_risk_reserve_ticket(host.load_intent(key), first_send_ticket)
        assert not host.consume_risk_reserve_ticket(host.load_intent(key), first_send_ticket)
        tickets.append(first_send_ticket)
        return GatewayClientResult('UNKNOWN')
    bound = MethodType(reserve, api)
    monkeypatch.setattr(api, 'risk_first_send_reserve_contract', lambda:
                        ('local-first-send-ticket-v1', bound, host.risk_first_send_host_contract()))
    broker.submit(order)
    assert host.load_execution_route(order.info['gateway_request_key']).kind == 'RISK'
    assert len(tickets) == 1 and calls == [] and order.status == order.Submitted


def test_direct_result_without_fresh_decision_cannot_reserve(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=False)
    monkeypatch.setattr(api, 'route_execution_order', lambda *a, **k:
                        ExecutionRoutingResult(ExecutionRoutingOutcome.DIRECT_PATH))
    broker.submit(order)
    assert host.load_execution_route(order.info['gateway_request_key']).kind == 'PENDING'
    assert order.status == order.Submitted and calls == []


def test_unresolved_parent_blocks_next_order_on_same_instrument(state, ready, inputs, monkeypatch):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    broker.submit(order)
    second = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    second.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    with pytest.raises(GatewayExecutionStreamError, match='ORDER_RECONCILE_REQUIRED'):
        broker.submit(second)
    assert second.status == second.Created and [c[0] for c in calls] == ['parent']


def test_proven_local_rejection_is_atomic_and_restored(state, ready, inputs, monkeypatch):
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _rebind
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    router._clock = lambda: 8000000000000000000
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert order.status == order.Rejected and calls == []
    assert host.load_execution_route(key).kind == 'EXECUTION_REJECTED'
    assert host.local_order_notifications()['reject:' + key]['code'] == 'EXECUTION_DEADLINE_EXPIRED'
    deliver(broker, strategy)
    deliver(broker, strategy)
    _, restored, new_strategy = _rebind(state, host, api, monkeypatch)
    recovered = restored._gateway_binding(new_strategy, required=True).orders[key]
    assert recovered.status == recovered.Rejected and recovered.executed.size == 0
    restored._gateway_cancel_order(recovered)
    assert not recovered.alive() and calls == []


def test_forged_rejection_does_not_finalize(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    monkeypatch.setattr(api, 'route_execution_order', lambda *a, **k:
        ExecutionRoutingResult(ExecutionRoutingOutcome.EXECUTION_REJECTED,
                               code='EXECUTION_DEADLINE_EXPIRED', rejection_decision=object()))
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert order.status == order.Submitted and host.load_execution_route(key).kind == 'PENDING'
    assert 'reject:' + key not in host.local_order_notifications() and calls == []


def test_rejection_write_failure_keeps_pending(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    router._clock = lambda: 8000000000000000000
    real_store = host._store._store
    def fail_rejection(value, *args, **kwargs):
        if any(route['kind'] == 'EXECUTION_REJECTED' for route in value['gateway'].get('execution_routes', {}).values()):
            raise OSError('synthetic write failure')
        return real_store(value, *args, **kwargs)
    monkeypatch.setattr(host._store, '_store', fail_rejection)
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert order.status == order.Submitted and host.load_execution_route(key).kind == 'PENDING'
    assert 'reject:' + key not in host.local_order_notifications() and calls == []


def test_rejection_notices_replay_in_order_after_restart(state, ready, inputs, monkeypatch):
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _rebind
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    router._clock = lambda: 8000000000000000000
    broker.submit(order)
    key = order.info['gateway_request_key']
    _, restored, new_strategy = _rebind(state, host, api, monkeypatch)
    recovered = restored._gateway_binding(new_strategy, required=True).orders[key]
    assert recovered.status == recovered.Rejected
    deliver(restored, new_strategy)
    deliver(restored, new_strategy)
    notices = host.local_order_notifications()
    assert notices[key]['status'] == notices['reject:' + key]['status'] == 'confirmed'
    assert calls == []


def test_rejection_token_is_bound_to_exact_code(state, ready, inputs, monkeypatch):
    from dataclasses import replace
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    router._clock = lambda: 8000000000000000000
    def changed_code(route, intent, *, before_submit):
        decision = router.route(intent, before_submit=before_submit)
        assert decision.rejection_decision is not None
        return replace(decision, code='EXECUTION_ORDER_INVALID')
    monkeypatch.setattr(api, 'route_execution_order', changed_code)
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert order.status == order.Submitted and host.load_execution_route(key).kind == 'PENDING'
    assert 'reject:' + key not in host.local_order_notifications() and calls == []


def test_stop_pending_does_not_report_cancel_attempt(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    monkeypatch.setattr(api, 'route_execution_order', lambda *a, **k:
                        ExecutionRoutingResult(ExecutionRoutingOutcome.EXECUTION_UNKNOWN))
    broker.submit(order)
    broker.p.stop_cancel_timeout = 0
    summary = broker._gateway_stop_working_orders()
    assert summary['cancel_requested'] == 0 and 'cancel_attempted_unknown' not in summary
    assert summary['refused']['EXECUTION_CANCEL_UNRESOLVED'] == 1
    assert summary['unresolved_working_orders'] == 1 and calls == []


def test_rejected_route_requires_matching_durable_notice(state, ready, inputs, monkeypatch):
    import copy
    from backtrader.live_state.atomic import LiveStateCorrupt
    from backtrader.live_state.pending import validate_pending_state
    host, api, data, broker, strategy, order, calls, router = setup_route(state, ready, inputs, monkeypatch, matched=True)
    router._clock = lambda: 8000000000000000000
    broker.submit(order)
    key = order.info['gateway_request_key']
    saved = host._store._load()
    for mutate in (lambda value: value['gateway']['local_notifications'].pop('reject:' + key),
                   lambda value: value['gateway']['execution_routes'][key].update(request_id='forged')):
        broken = copy.deepcopy(saved)
        mutate(broken)
        with pytest.raises(LiveStateCorrupt):
            validate_pending_state(broken, state.pending.path, state.strategy_uuid)
