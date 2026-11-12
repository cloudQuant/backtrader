"""Synthetic Gateway position ledger -> Registry -> SDK -> real BT getter.

Synthetic provider facts and continuity/baseline attestations exercise local
contracts only; no provider, account, credential, socket or retained host is used.
"""
import itertools
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import backtrader as bt
import bt_api_base
import bt_api_gateway
import bt_api_py
import pytest
from bt_api_base.direct_write_protocol import DirectExecutionEventKind, NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_protocol import GatewayReturnFact
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import (WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader,
    WireIdentity, WireMessageKind, WireRole, WireScope)
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant, ServiceCapability, ServiceRegistry
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_stream_consumer import framework
from tests.unit.test_iter65_gateway_strategy_value_prototype import make_session

WORKSPACE = Path(__file__).resolve().parents[3]
HELPERS = WORKSPACE / 'bt_api_py' / 'bt_api' / 'bt_api_gateway' / 'tests'
sys.path.insert(0, str(HELPERS))
try:
    from test_iter63_strategy_ledger_owner import KEY, BINDING, baseline, order
finally:
    sys.path.remove(str(HELPERS))

OP = 'direct.strategy_position'


def test_gateway_ledger_position_reaches_strategy_and_fails_closed(tmp_path, monkeypatch):
    for module in (bt, bt_api_base, bt_api_gateway, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE)
    (tmp_path / 'guards').mkdir()
    holder = {'continuous': True}

    def factory():
        guard = LocalAccountSessionGuard(tmp_path / 'guards', 'acct', 'owner')
        generation = guard.acquire()
        journal = GatewayDirectCommandJournal.create(tmp_path / 'db', 'acct', generation=generation)
        journal.enable_controls(guard)
        journal.enable_strategy_ledger(guard)
        journal.install_strategy_ledger_ports(guard=guard, resolve_binding=lambda _: BINDING,
            current_trading_day=lambda: '20300101', verify_day_transition=lambda *_: False,
            verify_current_continuity=lambda *_: holder['continuous'])
        def never_dispatch(*_args, **_kwargs):
            raise AssertionError('read prototype cannot dispatch')
        dispatcher = GatewayDirectDispatcher(journal, 'CTP', guard, never_dispatch,
                                             lambda _: ('synthetic-anchor',), lambda _: False)
        holder.update(journal=journal, guard=guard, ledger=GatewayDirectExecutionLedger(journal, guard))
        return GatewayDirectOwnerResources(dispatcher, journal, guard.release)

    owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=1, busy_timeout_seconds=1)
    assert owner.start(2)
    registry = None
    try:
        journal, guard, ledger = holder['journal'], holder['guard'], holder['ledger']
        identity = WireIdentity(WireRole.STRATEGY_CLIENT, 'p', 's1')
        scope = WireScope('synthetic-domain', account_ref='acct', strategy_ref='s1', run_id='run1')
        grant_scope = WireScope('synthetic-domain', account_ref='acct', strategy_ref='s1')
        ops = frozenset({OP})
        registry = ServiceRegistry(':memory:', service_id='gateway-service',
            capabilities=(ServiceCapability('gateway', 'service.direct_write', ops, frozenset()),),
            grants={'p': (PrincipalGrant(identity, (ResourceGrant('gateway', 'service.direct_write',
                'scope', grant_scope, ops),)),)}, policy_version='p', requirements_version='r')
        service = GatewayDirectServiceBinding(journal,
            {'p': GatewayDirectGrant('s1', frozenset({'rb2601'}))}, owner=owner)
        registry.register_handler('gateway', OP, lambda ctx, args: service.handle(OP, context=ctx, arguments=args))
        ids = itertools.count(1)
        def request(operation, payload):
            return WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                kind=WireMessageKind.REQUEST, message_id='message-' + str(next(ids)), correlation_id=None,
                identity=identity, scope=scope, operation=operation,
                schema_id='sdk.service.control' if operation.startswith('service.') else 'sdk.service.call',
                schema_version=1, sent_at_utc='2030-01-01T00:00:00Z'), payload=payload)
        registered = registry.handle('p', request('service.register', {
            'registration_key': 'synthetic-registration', 'client_session_id': 'synthetic-session',
            'instance_id': 'gateway', 'port': 'service.direct_write', 'scope_ref': 'scope',
            'operations': (OP,)}))
        assert registered['ok'], registered
        rec = registered['result']
        route = GatewayClientRoute('broker.direct_write', 'gateway-service', 'gateway', 'scope', scope, identity)
        bt_dir = tmp_path / 'bt-state'
        bt_dir.mkdir()
        state = StrategyStateDir.initialize(bt_dir)
        binding = GatewayCommandBinding(journal.journal_id, 'acct', 's1', 'p')
        GatewayPendingHost.upgrade_for_gateway(bt_dir, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(bt_dir, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref='p', actor_ref='s1',
            execution_domain_ref='synthetic-domain', account_scope='acct', strategy_scope='s1')
        host = GatewayPendingHost.upgrade_for_execution(bt_dir, state.strategy_uuid, binding, consumer_ref=consumer)
        session, api = make_session(host, route)
        registration = BindingSnapshot(rec['registration_id'], rec['service_epoch'], True, route.mount,
            route.service_id, route.instance_id, route.scope_ref, scope, ops, True)
        runtime = RuntimeSnapshot('running', True, True, None, (registration,), 0, 0, identity, 'run1')
        monkeypatch.setattr(session.runtime, 'status', lambda: runtime)
        calls = []
        def in_process_call(_mount, operation, arguments, **_kwargs):
            response = registry.handle('p', request(operation, {'registration_id': rec['registration_id'],
                'service_epoch': rec['service_epoch'], 'instance_id': 'gateway', 'arguments': arguments}))
            assert response['ok'], response
            calls.append(response['result'])
            return response['result']
        monkeypatch.setattr(session.runtime, 'call', in_process_call)
        data, broker, strategy = framework()
        broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
            contract_metadata={'rb2601': {'instrument_key': KEY.to_dict(),
                'exchange_name': 'CTP___FUTURE', 'quantity_unit': 'lots'}})
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
            orders_by_key={}, instrument_by_ref={'rb': KEY},
            time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'))
        def owner_call(fn):
            return owner.submit_service_call(fn).result(timeout_seconds=2)

        # Without an authenticated starting cut, zero cannot be inferred.
        with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNAVAILABLE'):
            strategy.get_strategy_position()
        assert calls[-1]['code'] == 'STRATEGY_LEDGER_UNAVAILABLE'
        owner_call(lambda: baseline(journal, guard))
        assert strategy.get_strategy_position().size == 0

        def reserve_and_start(key, side, offset, quantity):
            row = journal.reserve('s1', key, 'p', order(side, offset, quantity))
            native = {'exchange_name': 'CTP', 'client_order_id': key,
                      'session_generation': 1, 'fields_json': '{}'}
            journal.begin_dispatch('s1', key, row.reservation_id, row.digest, 'p', 1,
                                   native, (key + '-anchor',))
        def synthetic_fill(key, side, offset, quantity, trade):
            anchor = key + '-anchor'
            fact = GatewayReturnFact('acct', 'CTP', KEY, '20300101', DirectExecutionEventKind.TRADE,
                'synthetic-source-' + trade,
                identity=NativeOrderIdentity('CTP', key, {'trading_day': '20300101'}, 1),
                identity_keys=(anchor,), binding_keys=(anchor,), venue_key=anchor,
                trade_key=('SHFE', 'synthetic-' + trade), side=side, offset=offset,
                trade_quantity=quantity, trade_price='10')
            result = ledger.ingest(fact)
            assert result.disposition == 'ATTRIBUTED' and result.applied
        owner_call(lambda: reserve_and_start('open', 'buy', 'open', '2'))
        owner_call(lambda: synthetic_fill('open', 'buy', 'open', '2', 'open'))
        position = strategy.get_strategy_position()
        assert position.size == 2 and math.isnan(position.price)
        assert strategy.get_strategy_position(side='long').size == 2
        assert strategy.get_strategy_position(side='short').size == 0
        owner_call(lambda: reserve_and_start('close', 'sell', 'close_today', '2'))
        owner_call(lambda: synthetic_fill('close', 'sell', 'close_today', '1', 'partial'))
        assert strategy.get_strategy_position().size == 1
        owner_call(lambda: synthetic_fill('close', 'sell', 'close_today', '1', 'complete'))
        assert strategy.get_strategy_position().size == 0

        other = MarketInstrumentKey('ctp', 'SHFE', 'simnow', 'future', 'other', 'other')
        denied = api.get_strategy_position('CTP___FUTURE', other, quantity_unit='lots', timeout_seconds=1)
        assert denied.outcome == 'UNAVAILABLE' and denied.code == 'SCOPE_DENIED'
        wrong_venue = MarketInstrumentKey('ctp', 'DCE', 'simnow', 'future', 'rb2601', 'rb2601')
        denied = api.get_strategy_position('CTP___FUTURE', wrong_venue, quantity_unit='lots', timeout_seconds=1)
        assert denied.outcome == 'UNAVAILABLE' and denied.code == 'STRATEGY_LEDGER_UNAVAILABLE'
        metadata = broker.store.contract_metadata.pop('rb2601')
        with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNIT_UNAVAILABLE'):
            strategy.get_strategy_position()
        broker.store.contract_metadata['rb2601'] = {**metadata, 'quantity_unit': 'base'}
        with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNAVAILABLE'):
            strategy.get_strategy_position()
        assert calls[-1]['code'] == 'STRATEGY_LEDGER_UNAVAILABLE'
        broker.store.contract_metadata['rb2601'] = metadata
        assert strategy.get_strategy_position().size == 0
        holder['continuous'] = False
        with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNAVAILABLE'):
            strategy.get_strategy_position()
        assert calls[-1]['code'] == 'STRATEGY_LEDGER_UNAVAILABLE'
    finally:
        if registry is not None:
            registry.close()
        assert owner.close(2)
