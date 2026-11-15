"""Local two-process FAKE writer handoff and late Gateway parent request.

Synthetic grants/admission/transport; no provider, real account, network, crash,
or cross-host evidence. A releases normally; Gateway authority is independent.
"""
import base64
from dataclasses import replace
import itertools
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import (WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader,
    WireIdentity, WireMessageKind, WireRole, WireScope, decode_envelope)
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_parent_service import (GatewayParentGrant, GatewayParentService,
    GatewayParentSettings, OPERATIONS, REGISTER)
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant, ServiceCapability, ServiceRegistry

WORKSPACE = Path(__file__).resolve().parents[3]
CONDA = '/Users/yunjinqi/opt/anaconda3/bin/conda'

# Each worker creates its own store and authority on its own main thread.
CHILD = r'''
import base64, json, os, socket, sys, threading
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError('network/provider forbidden in FAKE prototype')
class NoNetwork(socket.socket):
    def __new__(cls, *args, **kwargs):
        forbidden()
socket.socket = NoNetwork
class BlockCtp:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('bt_api_ctp', '_ctp') or fullname.startswith('bt_api_ctp.'):
            raise AssertionError('CTP provider forbidden')
        return None
sys.meta_path.insert(0, BlockCtp())
from bt_api_base.service_protocol import (WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader,
    WireIdentity, WireMessageKind, WireRole, WireScope, encode_envelope)
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.errors import WriterLeaseUnavailable
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_py.gateway_delegate_service_client import GatewayDelegateRoute
from bt_api_py.gateway_parent_client import GatewayParentServiceClient
from bt_api_py.gateway_parent_service import OPERATIONS, REGISTER
from bt_api_py.gateway_parent_client import OPERATION
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot, ThreadedServiceClientRuntime
workspace = Path(sys.argv[1]).resolve()
assert Path(sys.executable).resolve() == Path('/Users/yunjinqi/opt/anaconda3/bin/python').resolve()
assert os.getpid() != int(sys.argv[3])
for name, module in tuple(sys.modules.items()):
    if name == 'bt_api' or name.startswith(('bt_api.', 'bt_api_')):
        paths = ([module.__file__] if getattr(module, '__file__', None) else [])
        paths.extend(getattr(module, '__path__', ()))
        assert all(Path(p).resolve().is_relative_to(workspace) for p in paths), name
assert not any(n in ('bt_api_ctp', '_ctp') or n.startswith('bt_api_ctp.') for n in sys.modules)
scope = ExecutionScope('FAKE', 'test', 'synthetic-account', 'synthetic-strategy', '20261109')
store = SqliteExecutionStore(sys.argv[2])
lease = authority = None

def reply(**data):
    print(json.dumps(data), flush=True)
reply(pid=os.getpid(), executable=str(Path(sys.executable).resolve()),
      store=str(Path(sys.modules[SqliteExecutionStore.__module__].__file__).resolve()),
      client=str(Path(sys.modules[GatewayParentServiceClient.__module__].__file__).resolve()))
try:
    for line in sys.stdin:
        cmd = json.loads(line)
        op = cmd['op']
        try:
            if op == 'acquire':
                lease = store.acquire_or_renew_lease(scope, cmd['owner'], ttl_ns=300_000_000_000)
                authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True)
                reply(status='acquired', token=lease.fencing_token)
            elif op == 'register':
                issued, parent = cmd['issued'], cmd['parent']
                identity = WireIdentity(WireRole.SERVICE, 'synthetic-principal', 'synthetic-actor')
                wire_scope = WireScope('synthetic-domain', account_ref='synthetic-account',
                                       strategy_ref='synthetic-strategy', run_id='synthetic-run')
                route = GatewayDelegateRoute('upstream.direct_write', 'synthetic-gateway',
                    'instance', 'scope', wire_scope, identity)
                runtime = ThreadedServiceClientRuntime(lambda: None)
                binding = BindingSnapshot(issued['registration_id'], issued['service_epoch'], True,
                    route.mount, route.service_id, route.instance_id, route.scope_ref, wire_scope, OPERATIONS, True)
                runtime.status = lambda: RuntimeSnapshot('running', True, True, None, (binding,), 0, 0,
                                                         identity, 'synthetic-run')
                captured = []
                def rpc(mount, operation, arguments, **kwargs):
                    assert operation == REGISTER and not captured
                    request = WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                        kind=WireMessageKind.REQUEST, message_id='synthetic-original-message', correlation_id=None,
                        identity=identity, scope=wire_scope, operation=operation, schema_id='sdk.service.call',
                        schema_version=1, sent_at_utc='2026-11-09T00:00:00Z'), payload={
                        'registration_id': issued['registration_id'], 'service_epoch': issued['service_epoch'],
                        'instance_id': 'instance', 'arguments': arguments})
                    captured.append(base64.b64encode(encode_envelope(request)).decode('ascii'))
                    raise TimeoutError('synthetic transport holds original request')
                runtime.call = rpc
                authority.bind_gateway(GatewayParentServiceClient(runtime, route=route, host=authority))
                assert authority.accept(parent)['gateway_state'] == 'PENDING'
                state = authority.register('parent-1')['gateway_state']
                assert len(captured) == 1
                reply(status='registered', state=state, envelope=captured[0])
            elif op == 'read':
                reply(status='read', state=authority.get('parent-1')['gateway_state'])
            elif op == 'reconcile':
                issued = cmd['issued']
                identity = WireIdentity(WireRole.SERVICE, 'synthetic-principal', 'synthetic-actor')
                wire_scope = WireScope('synthetic-domain', account_ref='synthetic-account',
                                       strategy_ref='synthetic-strategy', run_id='synthetic-run')
                route = GatewayDelegateRoute('upstream.direct_write', 'synthetic-gateway',
                    'instance', 'scope', wire_scope, identity)
                runtime = ThreadedServiceClientRuntime(lambda: None)
                binding = BindingSnapshot(issued['registration_id'], issued['service_epoch'], True,
                    route.mount, route.service_id, route.instance_id, route.scope_ref, wire_scope, OPERATIONS, True)
                runtime.status = lambda: RuntimeSnapshot('running', True, True, None, (binding,), 0, 0,
                                                         identity, 'synthetic-run')
                calls = []
                creator_thread = threading.get_ident()
                def rpc(mount, operation, arguments, **kwargs):
                    assert threading.get_ident() == creator_thread
                    assert operation == OPERATION and not calls
                    calls.append(operation)
                    request = WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                        kind=WireMessageKind.REQUEST, message_id='synthetic-reconcile-message', correlation_id=None,
                        identity=identity, scope=wire_scope, operation=operation, schema_id='sdk.service.call',
                        schema_version=1, sent_at_utc='2026-11-09T00:00:00Z'), payload={
                        'registration_id': issued['registration_id'], 'service_epoch': issued['service_epoch'],
                        'instance_id': 'instance', 'arguments': arguments})
                    reply(status='rpc', pid=os.getpid(), thread=creator_thread,
                          envelope=base64.b64encode(encode_envelope(request)).decode('ascii'))
                    response = json.loads(sys.stdin.readline())
                    assert response['op'] == 'rpc_result'
                    if not response['response']['ok']:
                        raise RuntimeError('synthetic transport received registry rejection')
                    return response['response']['result']
                runtime.call = rpc
                authority.bind_gateway(GatewayParentServiceClient(runtime, route=route, host=authority))
                assert authority.get('parent-1')['gateway_state'] == 'UNKNOWN'
                state = authority.reconcile('parent-1', 'gateway')['gateway_state']
                reply(status='reconciled', pid=os.getpid(), thread=threading.get_ident(),
                      state=state, calls=calls)
            elif op == 'stale_write':
                authority.accept(cmd['parent'])
                reply(status='unexpected_write')
            elif op == 'release':
                reply(status='released', released=store.release_lease(scope, lease.owner_id,
                                                                      fencing_token=lease.fencing_token))
            elif op == 'quit':
                reply(status='bye')
                break
            else:
                raise AssertionError('unknown command')
        except WriterLeaseUnavailable:
            reply(status='lease_unavailable')
finally:
    store.close()
'''


class Child:
    def __init__(self, database):
        python = Path('/Users/yunjinqi/opt/anaconda3/bin/python').resolve()
        sdk = WORKSPACE / 'bt_api_py'
        paths = [sdk, sdk / 'bt_api/bt_api_base/src', sdk / 'bt_api/bt_api_execution/src',
                 sdk / 'bt_api/bt_api_gateway/src']
        assert all(p.is_dir() for p in paths)
        env = {'PATH': str(python.parent) + ':/usr/bin:/bin', 'PYTHONPATH': os.pathsep.join(map(str, paths)),
               'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
        self.stderr = tempfile.TemporaryFile(mode='w+t')
        self.process = subprocess.Popen([CONDA, 'run', '--no-capture-output', '-n', 'base', 'python', '-u',
            '-c', CHILD, str(WORKSPACE), str(database), str(os.getpid())], cwd=sdk, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1,
            start_new_session=True)

    def receive(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            ready = selector.select(timeout=30)
        if not ready:
            raise AssertionError('child response timed out')
        line = self.process.stdout.readline()
        if not line:
            self.stderr.seek(0)
            raise AssertionError('child exited: ' + self.stderr.read())
        return json.loads(line)

    def request(self, op, **values):
        self.send(op, **values)
        return self.receive()

    def send(self, op, **values):
        assert self.process.poll() is None
        self.process.stdin.write(json.dumps({'op': op, **values}) + '\n')
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if self.process.poll() is None:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()


@pytest.mark.parametrize('revoke', [False, True], ids=['grant_active', 'principal_revoked'])
def test_late_parent_after_process_writer_handoff(tmp_path, monkeypatch, revoke):
    class NoNetwork(socket.socket):
        def __new__(cls, *args, **kwargs):
            raise AssertionError('network forbidden in FAKE prototype')
    monkeypatch.setattr(socket, 'socket', NoNetwork)
    assert WORKSPACE.name == 'wt-iter65'
    assert Path(sys.executable).resolve() == Path('/Users/yunjinqi/opt/anaconda3/bin/python').resolve()
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            assert not source or Path(source).resolve().is_relative_to(WORKSPACE), (name, source)
    account, strategy, domain = 'synthetic-account', 'synthetic-strategy', 'synthetic-domain'
    identity = WireIdentity(WireRole.SERVICE, 'synthetic-principal', 'synthetic-actor')
    wire_scope = WireScope(domain, account_ref=account, strategy_ref=strategy, run_id='synthetic-run')
    template = WireScope(domain, account_ref=account, strategy_ref=strategy)
    instrument = MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb', 'rb')
    parent = {'parent_ref': 'parent-1', 'registration_operation_id': 'register-1',
        'risk_operation_id': 'risk-1', 'account_scope': account, 'strategy_scope': strategy,
        'execution_domain_ref': domain, 'instrument': instrument.to_dict(), 'quantity': '5',
        'quantity_unit': 'lots', 'side': 'buy', 'offset': 'open', 'limit_price': '10',
        'creation_trading_day': '20261109', 'allowed_trading_days': ['20261109'],
        'expires_at_ns': time.time_ns() + 300_000_000_000, 'grant_revision': 'g1',
        'plan_digest': 'a' * 64, 'plan_version': 'v1', 'target_position_ref': None,
        'risk_selected': False, 'time_in_force': 'DAY'}
    guard_dir = tmp_path / 'guard'
    guard_dir.mkdir()
    parts = {}
    def factory():
        guard = LocalAccountSessionGuard(guard_dir, account, 'synthetic-gateway-owner')
        generation = guard.acquire()
        journal = GatewayDirectCommandJournal.create(tmp_path / 'gateway.sqlite', account, generation=generation)
        for method in ('enable_controls', 'enable_strategy_ledger', 'enable_account_extensions', 'enable_parent_authority'):
            getattr(journal, method)(guard)
        authority = GatewayParentAuthority(journal, guard, now_ns=time.time_ns,
            trading_day=lambda: '20261109', transfer_completed=lambda db, spec: '0', same_day_only=True)
        def never_place(*args):
            raise AssertionError('provider dispatch forbidden')
        dispatcher = GatewayDirectDispatcher(journal, 'CTP', guard, never_place,
                                               lambda identity: ('synthetic-anchor',), lambda row: False)
        parts.update(journal=journal, parent=authority)
        return GatewayDirectOwnerResources(dispatcher, journal, guard.release)
    owner = GatewayDirectOwner(factory, queue_size=4, max_queue_wait_seconds=2, busy_timeout_seconds=2)
    assert owner.start(2)
    registry = None
    children = []
    try:
        strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, 'synthetic-strategy-principal', strategy)
        strategy_ops = frozenset({'direct.reserve'})
        registry = ServiceRegistry(':memory:', service_id='synthetic-gateway', capabilities=(
            ServiceCapability('instance', 'service.direct_write', OPERATIONS | strategy_ops,
                              frozenset({REGISTER, 'direct.parent.cancel', 'direct.reserve'})),), grants={
            identity.principal_ref: (PrincipalGrant(identity, (ResourceGrant('instance',
                'service.direct_write', 'scope', template, OPERATIONS),)),),
            strategy_identity.principal_ref: (PrincipalGrant(strategy_identity, (ResourceGrant('instance',
                'service.direct_write', 'scope', template, strategy_ops),)),)},
            policy_version='synthetic-policy', requirements_version='synthetic-requirements')
        grant = GatewayParentGrant(identity, account, strategy, domain, 'execution', 'g1',
                                   frozenset({instrument}), OPERATIONS)
        service = GatewayParentService(GatewayParentSettings((grant,)), owner=owner, journal=parts['journal'],
                                       authority=parts['parent'], instance_id='instance', scope_ref='scope')
        service.configure(registry)
        for operation in OPERATIONS:
            registry.register_handler('instance', operation,
                                      lambda ctx, args, operation=operation: service.handle(operation, ctx, args))
        ids = itertools.count(1)
        def register(actor, key, operations):
            request = WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                kind=WireMessageKind.REQUEST, message_id='setup-' + str(next(ids)), correlation_id=None,
                identity=actor, scope=wire_scope, operation='service.register', schema_id='sdk.service.control',
                schema_version=1, sent_at_utc='2026-11-09T00:00:00Z'), payload={
                'registration_key': key, 'client_session_id': key + '-session', 'instance_id': 'instance',
                'port': 'service.direct_write', 'scope_ref': 'scope', 'operations': tuple(operations)})
            response = registry.handle(actor.principal_ref, request)
            assert response['ok'], response
            return response['result']
        register(strategy_identity, 'strategy-registration', strategy_ops)
        issued = register(identity, 'execution-registration', OPERATIONS)
        database = tmp_path / 'execution.sqlite'
        a = Child(database); children.append(a); a_info = a.receive()
        b = Child(database); children.append(b); b_info = b.receive()
        assert len({os.getpid(), a_info['pid'], b_info['pid']}) == 3
        for child, info in ((a, a_info), (b, b_info)):
            assert os.getpgid(info['pid']) == child.process.pid
            assert Path(info['executable']) == Path('/Users/yunjinqi/opt/anaconda3/bin/python').resolve()
            assert all(Path(info[k]).is_relative_to(WORKSPACE) for k in ('store', 'client'))
        old = a.request('acquire', owner='old-writer')
        captured = a.request('register', issued=issued, parent=parent)
        assert captured['status'] == 'registered' and captured['state'] == 'UNKNOWN'
        assert a.request('release') == {'status': 'released', 'released': True}
        new = b.request('acquire', owner='new-writer')
        assert new['status'] == 'acquired' and new['token'] > old['token']
        assert a.request('stale_write', parent=parent) == {'status': 'lease_unavailable'}
        assert b.request('read') == {'status': 'read', 'state': 'UNKNOWN'}
        request = decode_envelope(base64.b64decode(captured['envelope'], validate=True))
        assert request.header.identity == identity and request.header.scope == wire_scope
        assert request.header.operation == REGISTER
        assert request.payload['registration_id'] == issued['registration_id']
        assert request.payload['service_epoch'] == issued['service_epoch']
        assert request.payload['arguments']['spec']['parent_ref'] == 'parent-1'
        assert request.payload['arguments']['spec']['registration_operation_id'] == 'register-1'
        if revoke:
            assert registry.revoke_principal(identity.principal_ref) is True
        response = registry.handle(identity.principal_ref, request)
        if revoke:
            assert response['ok'] is False
        else:
            assert response['ok'], response
            assert response['result']['status'] == 'OBSERVED'
            assert response['result']['result']['state'] == 'ACTIVE'
            assert response['result']['result']['spec']['registration_operation_id'] == 'register-1'
            replay_request = WireEnvelope(
                header=replace(request.header, message_id='synthetic-replay-message'), payload=request.payload)
            assert replay_request.header.message_id != request.header.message_id
            assert replay_request.header.operation == request.header.operation
            assert replay_request.payload == request.payload
            replay = registry.handle(identity.principal_ref, replay_request)
            assert replay['ok'] and replay['result'] == response['result']
        b.send('reconcile', issued=issued)
        query = b.receive()
        assert query['status'] == 'rpc' and query['pid'] == b_info['pid']
        query_request = decode_envelope(base64.b64decode(query['envelope'], validate=True))
        assert query_request.header.identity == identity and query_request.header.scope == wire_scope
        assert query_request.header.operation == 'direct.parent.operation'
        assert query_request.header.message_id != request.header.message_id
        assert query_request.payload['registration_id'] == issued['registration_id']
        assert query_request.payload['service_epoch'] == issued['service_epoch']
        assert query_request.payload['instance_id'] == request.payload['instance_id']
        assert query_request.payload['arguments'] == {
            'account_scope': account, 'strategy_scope': strategy, 'parent_ref': 'parent-1',
            'registration_operation_id': 'register-1', 'operation_id': 'register-1'}
        query_response = registry.handle(identity.principal_ref, query_request)
        assert query_response['ok'] is not revoke
        if not revoke:
            assert query_response['result']['result']['operation_id'] == 'register-1'
            assert query_response['result']['result']['result']['state'] == 'ACTIVE'
        b.send('rpc_result', response=query_response)
        reconciled = b.receive()
        assert reconciled == {'status': 'reconciled', 'pid': b_info['pid'], 'thread': query['thread'],
                              'state': 'UNKNOWN' if revoke else 'ACCEPTED',
                              'calls': ['direct.parent.operation']}
        with sqlite3.connect(tmp_path / 'gateway.sqlite') as db:
            parents = db.execute('SELECT state FROM direct_execution_parents WHERE parent_ref=?', ('parent-1',)).fetchall()
            operations = db.execute('SELECT operation_id FROM direct_execution_parent_operations WHERE parent_ref=?', ('parent-1',)).fetchall()
        assert parents == ([] if revoke else [('ACTIVE',)])
        assert operations == ([] if revoke else [('register-1',)])
        assert b.request('read') == {'status': 'read', 'state': 'UNKNOWN' if revoke else 'ACCEPTED'}
        for child in children:
            assert child.request('quit') == {'status': 'bye'}
            assert child.process.wait(timeout=10) == 0
    finally:
        for child in children:
            child.close()
        if registry is not None:
            registry.close()
        assert owner.close(2)
