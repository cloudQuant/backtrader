"""Observation-only Gateway Broker prevents all order writes (synthetic state)."""
import backtrader as bt
import pytest

from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from tests.unit.brokers.test_gateway_execution_routing_lifecycle import setup_route
from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    INSTRUMENT, _bound_submit_fixture, api_for, framework, inputs, ready, state, strategy_dir,  # noqa: F401
)


def deny_writes(api, monkeypatch):
    for name in ('reserve_order', 'dispatch_order', 'release_order', 'cancel_order',
                 'route_execution_order', 'cancel_execution_order'):
        monkeypatch.setattr(api, name, lambda *a, _name=name, **kw: pytest.fail('write: ' + _name))


@pytest.mark.parametrize('selected', ['none', 'risk_execution'])
def test_public_and_private_submit_cancel_batch_never_send(state, ready, inputs, monkeypatch, selected):
    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    broker.set_param('market_data_only', True)
    if selected == 'risk_execution':
        monkeypatch.setattr(type(api), 'risk_selected', property(lambda _: True))
        monkeypatch.setattr(type(api), 'execution_selected', property(lambda _: True))
    deny_writes(api, monkeypatch)
    before = host._store._load()
    new = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    assert broker.submit(new).status == new.Rejected
    new2 = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    assert broker._gateway_submit_order(new2).status == new2.Rejected
    working = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    working.submit(broker)
    broker.orders[working.ref] = working
    assert broker.submit(working) is working and working.status == working.Submitted
    assert broker.cancel(working) is working and working.status == working.Submitted
    assert broker._gateway_cancel_order(working) is working and working.status == working.Submitted
    assert broker.batch_cancel([working]) == []
    assert host._store._load() == before and working.executed.size == 0
    assert not broker._trading_enabled


@pytest.mark.parametrize('kind', ['parent', 'parent_risk', 'gateway'])
def test_existing_orders_recovery_and_stop_are_observation_only(state, ready, inputs, monkeypatch, kind):
    host, api, data, broker, strategy, order, calls, router = setup_route(
        state, ready, inputs, monkeypatch, matched=(kind != 'gateway'))
    broker.submit(order)
    key = order.info['gateway_request_key']
    assert host.load_execution_route(key).kind == ('GATEWAY' if kind == 'gateway' else 'EXECUTION_PARENT')
    if kind == 'parent_risk':
        monkeypatch.setattr(type(api), 'risk_selected', property(lambda _: True))
    broker.set_param('market_data_only', True)
    deny_writes(api, monkeypatch)
    before = host._store._load()
    order_status = order.status
    assert broker.cancel(order) is order and order.status == order_status
    assert broker._gateway_release_unsent(broker._gateway_stream_binding, order, key) is False
    broker._gateway_finalize_release(broker._gateway_stream_binding, order, key)
    broker._gateway_finalize_rejection(broker._gateway_stream_binding, order, key, 'NOT_FOUND')
    assert order.status == order_status and order.executed.size == 0
    summary = broker._gateway_stop_working_orders()
    assert summary['cancel_requested'] == 0 and summary['unresolved_working_orders'] == 1
    assert host._store._load() == before


def test_start_failure_and_stop_retry_cleanup_without_order_writes(monkeypatch):
    _, broker, _ = framework()
    broker.set_param('market_data_only', True)
    class Store:
        _gateway_mode = True
        _cerebro_managed_lifecycle = True
        def __init__(self):
            self.starts = 0
            self.stops = 0
        @property
        def is_connected(self):
            if self.stops < 2:
                raise RuntimeError('synthetic uncertain status')
            return False
        def start(self, **kwargs):
            self.starts += 1
            raise RuntimeError('synthetic failed startup')
        def stop(self, **kwargs):
            self.stops += 1
            return {'shutdown_state': 'INCOMPLETE' if self.stops == 1 else 'PASS'}
    store = broker.store = Store()
    with pytest.raises(RuntimeError, match='synthetic failed startup'):
        broker.start()
    assert not broker._trading_enabled
    with pytest.raises(ValueError, match='frozen'):
        broker.set_param('market_data_only', False)
    first = broker.stop()
    assert first['store_shutdown_state'] == 'INCOMPLETE' and store.stops == 1
    second = broker.stop()
    assert second['store_shutdown_state'] == 'PASS' and store.stops == 2
    assert broker.stop()['store_shutdown_state'] == 'PASS' and store.stops == 2


@pytest.mark.parametrize('kind', ['parent', 'gateway'])
def test_next_and_real_stop_do_not_dispose_restored_work(state, ready, inputs, monkeypatch, kind):
    from bt_api_py.gateway_execution_stream_client import GatewayExecutionReadContext, GatewayExecutionStreamClientResult
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import deliver, page
    from tests.unit.live_state.test_gateway_pending import observe
    host, api, data, broker, strategy, order, calls, router = setup_route(
        state, ready, inputs, monkeypatch, matched=(kind == 'parent'))
    broker.submit(order)
    key = order.info['gateway_request_key']
    if kind == 'gateway':
        host.save_record(key, observe(host.load_intent(key)))
    deliver(broker, strategy)
    broker.set_param('market_data_only', True)
    deny_writes(api, monkeypatch)
    monkeypatch.setattr(api, 'command_status', lambda *a, **k: pytest.fail('reconciliation should stay pending'))
    stream = broker._gateway_stream_binding.stream
    _, binding, consumer = ready
    monkeypatch.setattr(stream, 'read_after', lambda after, epoch, limit, *, timeout_seconds:
        GatewayExecutionStreamClientResult('OBSERVED', page=page(binding, consumer, []),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit)))
    before = host._store._load()
    broker.next()
    assert broker.gateway_execution_stream_status() == 'OBSERVATION_ONLY_RECOVERY_PENDING'
    after = host._store._load()
    for field in ('intents', 'order_snapshots', 'local_notifications', 'execution_routes', 'delegated_commands'):
        assert after['gateway'][field] == before['gateway'][field]
    assert order.status == order.Submitted
    before = after
    stopped = []
    broker.store._gateway_mode = True
    broker.store.is_connected = True
    broker.store.stop = lambda **kwargs: stopped.append(True) or {'shutdown_state': 'PASS'}
    broker._live_started = True
    broker._market_gateway_cleanup_pending = True
    summary = broker.stop()
    assert stopped == [True] and summary['cancel_requested'] == summary['close_requested'] == 0
    assert summary['active_order_count'] == 1 and summary['unknown_orders'] is None
    assert summary['remote_flat_proven'] is False and order.status == order.Submitted
    assert host._store._load() == before


def test_read_only_restore_does_not_finalize_expired_reservation(state, ready, inputs, monkeypatch):
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import deliver
    from tests.unit.live_state.test_gateway_pending import observe
    host, api, data, broker, strategy, order, calls, router = setup_route(
        state, ready, inputs, monkeypatch, matched=False)
    broker.submit(order)
    key = order.info['gateway_request_key']
    host.save_record(key, observe(host.load_intent(key), state='EXPIRED', version=2))
    deliver(broker, strategy)
    before = host._store._load()
    data2, broker2, strategy2 = framework()
    broker2.set_param('market_data_only', True)
    deny_writes(api, monkeypatch)
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    restored = broker2._gateway_binding(strategy2, required=True).orders[key]
    assert restored.status == restored.Submitted and restored.executed.size == 0
    assert 'cancel:' + key not in host.local_order_notifications() and host._store._load() == before


def test_unbound_public_writes_do_not_trigger_gateway_binding(monkeypatch):
    data, broker, strategy = framework()
    broker.set_param('market_data_only', True)
    broker.store._gateway_mode = True
    monkeypatch.setattr(broker, '_gateway_auto_bind', lambda *a, **k: pytest.fail('must not bind for write'))
    new = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    broker.submit(new)
    assert new.status == new.Rejected
    previous = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    previous.submit(broker)
    assert broker.cancel(previous) is previous and previous.status == previous.Submitted
    assert broker.batch_cancel([previous]) == []


def test_gateway_start_remains_read_only_and_stops_normally():
    _, broker, _ = framework()
    broker.set_param('market_data_only', True)
    class Store:
        _gateway_mode = True
        _cerebro_managed_lifecycle = True
        is_connected = False
        def __init__(self):
            self.stops = 0
        def start(self, **kwargs):
            self.is_connected = True
        def stop(self, **kwargs):
            self.stops += 1
            self.is_connected = False
            return {'shutdown_state': 'PASS'}
    store = broker.store = Store()
    broker.start()
    assert broker._live_started and not broker._trading_enabled and not broker._startup_ready
    with pytest.raises(ValueError, match='frozen'):
        broker.set_param('market_data_only', False)
    summary = broker.stop()
    assert store.stops == 1 and summary['store_shutdown_state'] == 'PASS'
    assert summary['cancel_requested'] == 0 and summary['remote_flat_proven'] is False


def test_other_private_and_group_write_entries_are_blocked(state, ready, inputs, monkeypatch):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    broker.set_param('market_data_only', True)
    deny_writes(api, monkeypatch)
    working = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    working.submit(broker)
    binding = broker._gateway_stream_binding
    assert broker._gateway_risk_cancel(binding, working, 'any') is working
    assert working.status == working.Submitted
    with pytest.raises(GatewayExecutionStreamError, match='MARKET_DATA_ONLY'):
        broker._gateway_risk_prepare(binding, 'any', object())
    with pytest.raises(ValueError, match='market_data_only'):
        broker._cancel_remote_open_order({'order_id': 'id', 'symbol': 'rb'})
    with pytest.raises(ValueError, match='market_data_only'):
        broker.submit_group_order(strategy, object())
    with pytest.raises(ValueError, match='market_data_only'):
        broker.submit_group_roll_exit(strategy, 'group', 'leg', 10)
