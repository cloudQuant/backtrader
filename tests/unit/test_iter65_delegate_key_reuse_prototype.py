"""65.01 sequential, offline observation of Execution delegate key reuse.

Execution store/authority/host and SDK clients are real local components.
Admission, registration response, runtime binding and RPC transport are synthetic;
no real Registry, Gateway, Risk, provider, network or account is involved.
"""
from decimal import Decimal
import json
from pathlib import Path
import sys
import time

import pytest

from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
from bt_api_base.gateway_direct_protocol import canonical_gateway_payload, gateway_payload_digest
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution.contracts import ExecutionScope, canonical_json, payload_sha256
from bt_api_execution.errors import ContractValidationError, IntentConflictError, InvalidStateTransition
from bt_api_execution.gateway_delegate_host import ExecutionGatewayDelegateHost
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_delegate_service_client import (
    GatewayDelegateIntent, GatewayDelegateRoute, GatewayDelegateServiceClient,
)
from bt_api_py.gateway_parent_client import GatewayParentServiceClient
from bt_api_py.gateway_parent_service import CANCEL, OPERATION, REGISTER
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot, ThreadedServiceClientRuntime

ACCOUNT, STRATEGY, DOMAIN = 'synthetic-account', 'synthetic-strategy', 'synthetic-domain'
KEY = 'synthetic-request-key'
INSTRUMENT = MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb', 'rb')
IDENTITY = WireIdentity(WireRole.SERVICE, 'synthetic-exec', 'synthetic-actor')


@pytest.fixture(scope='module', autouse=True)
def isolated_sources():
    yield
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == 'wt-iter65'
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            if source and not Path(source).resolve().is_relative_to(workspace):
                escaped[name] = source
    assert not escaped, escaped


def parent(parent_id, quantity):
    return dict(parent_ref=parent_id, registration_operation_id='register-' + parent_id,
        risk_operation_id='risk-' + parent_id, account_scope=ACCOUNT, strategy_scope=STRATEGY,
        execution_domain_ref=DOMAIN, instrument=INSTRUMENT.to_dict(), quantity=quantity,
        quantity_unit='lots', side='buy', offset='open', limit_price='10',
        creation_trading_day='20261109', allowed_trading_days=['20261109'],
        expires_at_ns=time.time_ns() + 3_600_000_000_000, grant_revision='g1',
        plan_digest='a' * 64, plan_version='v1', target_position_ref=None,
        risk_selected=False, time_in_force='DAY')


def request():
    return OrderRequest(symbol='rb', side=Side.BUY, order_type=OrderType.LIMIT,
        quantity=Decimal('1'), account_id=ACCOUNT, client_order_id='synthetic-client',
        price=Decimal('10'), idempotency_key=KEY, quantity_unit='lots', offset='open', exchange_id='SHFE')


def command(parent_id, child_id, digest):
    return GatewayDelegatedCommand(ACCOUNT, STRATEGY, DOMAIN, IDENTITY.principal_ref,
        IDENTITY.actor_ref, 'execution', 'synthetic-run', KEY, digest, INSTRUMENT,
        'g1', parent_id, child_id)


def child(child_id, digest, *, request_key=KEY):
    return dict(child_id=child_id, request_key=request_key, trading_day='20261109',
        offset='open', quantity='1', payload_digest=digest)


def rows(store, authority):
    return [dict(row) for row in store._connection.execute(
        'SELECT parent_id, child_id, request_json, state, quantity, filled_quantity '
        'FROM execution_parent_children WHERE scope_key=? ORDER BY parent_id, child_id',
        (authority.parent_scope_key,)).fetchall()]


@pytest.mark.parametrize('separate_parents', [False, True], ids=['legacy-same-parent-unknown', 'different-parents'])
def test_reused_delegate_key_preserves_original_intent_and_occupied_children(tmp_path, monkeypatch, separate_parents):
    scope = ExecutionScope('FAKE', 'test', ACCOUNT, STRATEGY, '20261109')
    wire_scope = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY, run_id='synthetic-run')
    route = GatewayDelegateRoute('upstream.direct_write', 'synthetic-gateway', 'instance',
                                 'scope', wire_scope, IDENTITY)
    operations = frozenset({REGISTER, OPERATION, CANCEL, 'direct.delegated_reserve', 'direct.delegated_dispatch'})
    binding = BindingSnapshot('synthetic-registration', 'synthetic-epoch', True, route.mount,
        route.service_id, route.instance_id, route.scope_ref, wire_scope, operations, True)
    runtime = ThreadedServiceClientRuntime(lambda: None)  # never started; methods below are in-process fakes
    monkeypatch.setattr(runtime, 'status', lambda: RuntimeSnapshot('running', True, True, None,
        (binding,), 0, 0, IDENTITY, 'synthetic-run'))
    calls = []

    def fake_call(_mount, operation, args, **_kwargs):
        calls.append(operation)
        if operation == REGISTER:
            wire = args['spec']
            return {'status': 'OBSERVED', 'schema_version': 1, 'operation': operation,
                'result': {'spec': wire, 'spec_digest': gateway_payload_digest(wire),
                    'execution_principal': IDENTITY.principal_ref, 'execution_actor_ref': IDENTITY.actor_ref,
                    'state': 'ACTIVE', 'version': 1}}
        assert operation == 'direct.delegated_reserve'
        return {'status': 'UNKNOWN'}  # no assertion that Gateway received or stored anything

    monkeypatch.setattr(runtime, 'call', fake_call)
    path = tmp_path / 'execution.sqlite'
    store = SqliteExecutionStore(path)
    try:
        lease = store.acquire_or_renew_lease(scope, 'synthetic-writer', ttl_ns=300_000_000_000)
        authority = ParentAuthority(store, scope, lease, admission=lambda _action, _value: True)
        authority.bind_gateway(GatewayParentServiceClient(runtime, route=route, host=authority))
        first_parent, second_parent = 'parent-a', 'parent-b' if separate_parents else 'parent-a'
        for parent_id in dict.fromkeys((first_parent, second_parent)):
            authority.accept(parent(parent_id, '1' if separate_parents else '2'))
            assert authority.register(parent_id)['gateway_state'] == 'ACCEPTED'
        parent_calls = calls.copy()
        assert parent_calls == [REGISTER] * (2 if separate_parents else 1)
        order = request()
        digest = gateway_payload_digest(order.to_dict())
        first_id, second_id = KEY, KEY if separate_parents else 'legacy-child'
        first = command(first_parent, first_id, digest)
        second = command(second_parent, second_id, digest)
        assert authority.prepare_child(first_parent, child(first_id, digest))['state'] == 'PREPARED'
        if separate_parents:
            assert authority.prepare_child(second_parent, child(second_id, digest))['state'] == 'PREPARED'
        else:
            # Current admission cannot create the unequal-key historical record.
            with pytest.raises(ContractValidationError, match='child request_key'):
                authority.prepare_child(second_parent, child(second_id, digest))
            assert len(rows(store, authority)) == 1
        host = ExecutionGatewayDelegateHost(authority)
        client = GatewayDelegateServiceClient(runtime, route=route, host=host)
        first_result = authority.dispatch_child(first_parent, first_id, first, order, client)
        assert first_result.outcome == 'UNKNOWN'
        assert calls == parent_calls + ['direct.delegated_reserve']
        saved = host.load_delegate_intent(KEY)
        assert saved.command == first
        assert host.load_delegate_observation(KEY) is None
        assert host.load_delegate_dispatch_marker(KEY) is None

        if separate_parents:
            second_result = authority.dispatch_child(second_parent, second_id, second, order, client)
        else:
            # Simulate a child claimed by an older version. The row is already
            # UNKNOWN; it is not evidence that current admission can claim it.
            legacy = child(second_id, digest)
            with store._transaction() as cursor:
                cursor.execute('INSERT INTO execution_parent_children VALUES (?,?,?,?,?,?,?,?,?)',
                    (authority.parent_scope_key, second_parent, second_id, canonical_json(legacy),
                     payload_sha256(legacy), '1', '0', 'UNKNOWN', time.time_ns()))
            with pytest.raises(InvalidStateTransition, match='child is not prepared'):
                authority.claim_child(second_parent, second_id)
            second_result = client.reserve(second, order)
        assert (second_result.outcome, second_result.code) == ('TRANSPORT_NOT_STARTED', 'INTENT_NOT_DURABLE')
        assert calls == parent_calls + ['direct.delegated_reserve']
        assert host.load_delegate_intent(KEY) == saved
        conflict = GatewayDelegateIntent(route, second, canonical_gateway_payload(order.to_dict()), 10.0)
        # This independent host API probe is not the SDK client's path above:
        # the client itself detects the old intent without calling save again.
        with pytest.raises(IntentConflictError, match='delegate key was reused'):
            host.save_delegate_intent(conflict)
        before = rows(store, authority)
        assert [(r['parent_id'], r['child_id'], r['state'], r['quantity'], r['filled_quantity']) for r in before] == sorted([
            (first_parent, first_id, 'UNKNOWN', '1', '0'),
            (second_parent, second_id, 'UNKNOWN', '1', '0')])
        assert all(json.loads(r['request_json'])['request_key'] == KEY for r in before)
        for parent_id in dict.fromkeys((first_parent, second_parent)):
            with pytest.raises(InvalidStateTransition, match='parent capacity exhausted'):
                authority.prepare_child(parent_id, child('child-extra', digest, request_key='child-extra'))
    finally:
        store.close()

    store = SqliteExecutionStore(path)
    try:
        lease = store.acquire_or_renew_lease(scope, 'synthetic-writer', ttl_ns=300_000_000_000)
        authority = ParentAuthority(store, scope, lease, admission=lambda _action, _value: True)
        host = ExecutionGatewayDelegateHost(authority)
        assert host.load_delegate_intent(KEY) == saved
        assert host.load_delegate_observation(KEY) is None
        assert host.load_delegate_dispatch_marker(KEY) is None
        assert rows(store, authority) == before
        client = GatewayDelegateServiceClient(runtime, route=route, host=host)
        for parent_id, child_id, original in ((first_parent, first_id, first),
                                              (second_parent, second_id, second)):
            error, message = ((ContractValidationError, 'delegate child identity mismatch')
                              if original.request_key != child_id
                              else (InvalidStateTransition, 'child is not prepared'))
            with pytest.raises(error, match=message):
                authority.dispatch_child(parent_id, child_id, original, order, client)
            assert rows(store, authority) == before
        for parent_id in dict.fromkeys((first_parent, second_parent)):
            with pytest.raises(InvalidStateTransition, match='parent capacity exhausted'):
                authority.prepare_child(parent_id, child('child-extra', digest, request_key='child-extra'))
        assert calls == parent_calls + ['direct.delegated_reserve']
    finally:
        store.close()
