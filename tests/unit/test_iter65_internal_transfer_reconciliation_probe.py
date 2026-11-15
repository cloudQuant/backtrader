"""Offline probe of Broker reconciliation with an independent transfer candidate.

All observations are synthetic mappings, not SDK provenance or account evidence.
The extension is deliberately not represented as a provider fill.  In particular,
clearing the reconciliation barrier does not establish transfer consumption.
"""
from copy import deepcopy
from pathlib import Path

import backtrader as bt
import pytest
import bt_api_base
import bt_api_py

from tests.unit.brokers.test_iter63_gateway_stream_consumer import attach, framework
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs


def _files(directory):
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in Path(directory).rglob('*') if p.is_file()}


def _observation(order, side, index, filled):
    return {
        'local_ref': order.ref, 'client_order_id': f'client-{index}',
        'intent_ref': f'parent-{index}', 'data_name': 'rb',
        'order': {'order_id': f'venue-order-{index}', 'instrument_ref': 'rb',
                  'symbol': 'rb', 'side': side, 'quantity': '1',
                  'filled_quantity': filled, 'quantity_unit': 'lots', 'price': '10',
                  'status': 'open' if filled == '0' else 'partially_filled',
                  'terminal_confirmed': False},
    }


@pytest.mark.parametrize('include_transfer', [True, False], ids=['transfer-extension', 'no-extension-control'])
@pytest.mark.parametrize('filled', ['0', '0.5'], ids=['venue-cumulative-unchanged', 'cumulative-includes-transfer'])
def test_independent_transfer_is_not_a_provider_fill(state, ready, inputs, monkeypatch, filled, include_transfer):
    workspace = Path(__file__).resolve().parents[3]
    # The workspace holds this repository and the sibling SDK checkout.
    assert (workspace / 'backtrader').is_dir() and (workspace / 'bt_api_py').is_dir()
    for module in (bt, bt_api_py, bt_api_base):
        assert Path(module.__file__).resolve().is_relative_to(workspace)
    host, broker, strategy_a, buy, calls, _ = attach(ready, inputs, monkeypatch, events=())
    _, _, strategy_b = framework()
    sell = bt.SellOrder(owner=strategy_b, data=buy.data, size=1, price=10,
                        exectype=bt.Order.Limit)
    sell.addcomminfo(broker.getcommissioninfo(buy.data))
    sell.submit(broker)
    sell.accept(broker)
    broker.orders[sell.ref] = sell
    broker._position_quantity_units['rb'] = 'lots'
    broker._begin_execution_reconciliation('synthetic_probe')

    candidate = {
        'kind': 'internal_transfer', 'source': 'independent_internal_transfer',
        'transfer_id': 'transfer-1', 'instrument_ref': 'rb',
        'price': '10', 'quantity': '0.5', 'quantity_unit': 'lots',
        'legs': [
            {'strategy_ref': 'strategy-a', 'parent_ref': 'parent-1', 'side': 'buy', 'quantity': '0.5'},
            {'strategy_ref': 'strategy-b', 'parent_ref': 'parent-2', 'side': 'sell', 'quantity': '0.5'},
        ],
    }
    snapshot = {'complete': True, 'safe_to_resume': True,
                'consistency_digest': 'synthetic-same-digest', 'snapshot_id': 'cut-1',
                'orders': [_observation(buy, 'buy', 1, filled),
                           _observation(sell, 'sell', 2, filled)],
                'fills': [], 'positions': []}
    if include_transfer:
        snapshot['internal_transfers'] = [candidate]
    before_files = _files(state.strategy_dir)
    before_checkpoint = host.load_execution_checkpoint()
    before_orders = host.iter_order_snapshots()
    before = [(o.status, o.executed.size, len(o.executed.exbits)) for o in (buy, sell)]
    assert before == [(buy.Accepted, 0, 0), (sell.Accepted, 0, 0)]
    assert not strategy_a._trades and not strategy_b._trades
    assert not broker.notifs and not strategy_a._orderspending and not strategy_b._orderspending

    first = broker.record_reconciliation(deepcopy(snapshot))
    assert first['required'] and first['consecutive_complete_rounds'] == 1
    assert first['reason'] == 'awaiting_second_consistent_snapshot'
    assert [(o.status, o.executed.size, len(o.executed.exbits)) for o in (buy, sell)] == before
    snapshot['snapshot_id'] = 'cut-2'
    second = broker.record_reconciliation(snapshot)
    if filled == '0':
        assert second['complete'] and second['consecutive_complete_rounds'] == 2
        assert second['reason'] == 'two_sdk_verified_snapshots_agree'
    else:
        assert second['required'] and second['consecutive_complete_rounds'] == 0
        assert second['reason'] == 'order_fill_coverage_mismatch'

    assert [(o.status, o.executed.size, len(o.executed.exbits)) for o in (buy, sell)] == before
    assert broker.positions['rb'].size == 0
    assert not strategy_a._trades and not strategy_b._trades
    assert not broker.notifs and not strategy_a._orderspending and not strategy_b._orderspending
    assert not strategy_a.events and not strategy_b.events
    assert host.load_execution_checkpoint() == before_checkpoint
    assert host.iter_order_snapshots() == before_orders
    assert _files(state.strategy_dir) == before_files
    assert calls['ack'] == [] and calls['read'] == 0
