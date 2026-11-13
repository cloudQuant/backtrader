"""Offline Gateway/managed-adapter routing probe using actual Store and Broker.

The adapter event and SDK transport results are synthetic. This is not proof of
an independent transfer source, a real Gateway, account, or production behavior.
"""
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt
import bt_api_base
import bt_api_py
import pytest
import yaml

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext, GatewayExecutionStreamClientResult,
)
from bt_api_py.gateway_strategy_config import GatewayStrategyConfig, parse_gateway_strategy_config
from bt_api_py.service_runtime import ClientCurveKeys
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import page


class RecordingAdapter:
    """Synthetic outbox; no provider fill or network access."""
    def __init__(self):
        self.calls = []
        self.event = {
            'kind': 'internal_transfer', 'source': 'independent_internal_transfer',
            'transfer_id': 'synthetic-transfer-1', 'price': '10', 'quantity': '0.5',
            'legs': [{'strategy_ref': 'a', 'parent_ref': 'parent-a', 'side': 'buy'},
                     {'strategy_ref': 'b', 'parent_ref': 'parent-b', 'side': 'sell'}],
        }

    def submit_order(self, order, sdk_dispatch):
        self.calls.append('submit')
        raise AssertionError('synthetic adapter must not dispatch')

    def cancel_order(self, order_or_ref, dataname, sdk_dispatch):
        self.calls.append('cancel')
        raise AssertionError('synthetic adapter must not dispatch')

    def poll_managed_provider_outbox_update(self):
        self.calls.append('poll')
        return dict(self.event)


@pytest.fixture
def gateway(state):
    workspace = Path(__file__).resolve().parents[3]
    for module in (bt, bt_api_py, bt_api_base):
        assert Path(module.__file__).resolve().is_relative_to(workspace)
    example = workspace / 'bt_api_py/examples/services/gateway-strategy-client.example.yaml'
    config = yaml.safe_load(example.read_text(encoding='utf-8'))
    parsed = parse_gateway_strategy_config(config)
    binding = GatewayCommandBinding(**config['binding'])
    route = parsed.route
    consumer = gateway_execution_consumer_ref(
        principal_ref=route.identity.principal_ref, actor_ref=route.identity.actor_ref,
        execution_domain_ref=route.scope.execution_domain_ref,
        account_scope=binding.account_scope, strategy_scope=binding.strategy_scope,
    )
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_execution(state.strategy_dir, state.strategy_uuid, binding,
                                               consumer_ref=consumer)
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    keys = {'security': ClientCurveKeys(b'a' * 40, b'b' * 40, b'c' * 40)}
    return config, host, keys, binding, consumer


def test_gateway_constructor_refuses_managed_adapter(gateway):
    config, host, keys, _, _ = gateway
    adapter = RecordingAdapter()
    with pytest.raises(BtApiStoreError, match='GATEWAY_CONFIGURATION_CONFLICT'):
        BtApiStore(config={'gateway_strategy': config}, gateway_host=host,
                   gateway_security_profiles=keys, managed_execution_adapter=adapter)
    assert adapter.calls == []


def test_late_attached_outbox_is_not_drained_by_gateway_next(gateway, monkeypatch):
    config, host, keys, binding, consumer = gateway
    control = RecordingAdapter()
    event = control.poll_managed_provider_outbox_update()
    assert control.calls == ['poll'] and event['kind'] == 'internal_transfer'
    assert event['source'] == 'independent_internal_transfer' and 'trade_id' not in event

    adapter = RecordingAdapter()
    store = BtApiStore(config={'gateway_strategy': config}, gateway_host=host,
                       gateway_security_profiles=keys)
    store.attach_managed_execution_adapter(adapter)
    assert store._managed_execution_adapter is adapter and store._gateway_mode
    parsed = parse_gateway_strategy_config(config)
    # Construct the real SDK facade, but replace its runtime I/O by inert synthetic
    # status and stream results before the real Store/Broker lifecycle starts.
    api = parsed.create_api(host=host, cancel_host=host, security_profiles=keys)
    running = SimpleNamespace(state='running', healthy=True, thread_alive=True,
                              cleanup_failures=0, unregister_uncertainties=0,
                              owner_cleanup_uncertainties=0)
    closed = SimpleNamespace(state='closed', healthy=False, thread_alive=False,
                             cleanup_failures=0, unregister_uncertainties=0,
                             owner_cleanup_uncertainties=0)
    monkeypatch.setattr(GatewayStrategyConfig, 'create_api', lambda *_a, **_kw: api)
    monkeypatch.setattr(api, 'start', lambda **_kw: running)
    monkeypatch.setattr(api, 'status', lambda: running)
    monkeypatch.setattr(api, 'close', lambda **_kw: closed)
    stream = api.gateway_execution_stream(config['exchange_name'])
    reads = []
    def read(after, epoch, limit, *, timeout_seconds):
        reads.append((after, epoch, limit))
        return GatewayExecutionStreamClientResult(
            'OBSERVED', page=page(binding, consumer, ()),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))
    monkeypatch.setattr(stream, 'read_after', read)

    data, _, strategy = framework()
    data._name = 'main'
    broker = store.getbroker()
    strategy.broker = broker
    before = host.load_execution_checkpoint()
    broker.start()
    try:
        assert store.is_connected and store.gateway_api is api
        store.bind_gateway_strategy(strategy, data_by_ref={'main': data}, orders_by_key={})
        broker.next()
        assert len(reads) == 1
        assert adapter.calls == []
        assert not broker.notifs and not strategy._trades and not strategy._orderspending
        assert not strategy.events and not broker.positions
        assert host.load_execution_checkpoint().applied_sequence == before.applied_sequence
        assert host.load_execution_checkpoint().acknowledged_sequence == before.acknowledged_sequence
    finally:
        broker.stop()
    assert not store.is_connected and adapter.calls == []
