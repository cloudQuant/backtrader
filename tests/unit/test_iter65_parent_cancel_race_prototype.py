"""65.01 local ordering experiments, not a real transport or authorization.

Real Execution and Gateway SQLite owners and the SDK parent client are joined
by a synthetic in-process transport, registration snapshot and admission port.
The Gateway owner runs on its own thread. Held messages simulate one possible
late delivery; no provider, network, real account or source proof is involved.
Only the explicitly synchronized orders below are observed. They do not prove
all races, independent stop barriers, dual leases or absence of late effects.
"""

from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
import sys
import threading
import time

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_parent_authority import GatewayParentAuthority, GatewayParentError
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_delegate_service_client import GatewayDelegateRoute
from bt_api_py.gateway_parent_client import GatewayParentServiceClient
from bt_api_py.gateway_parent_service import REGISTER, CANCEL, OPERATION, QUERY
from bt_api_py.service_runtime_thread import ThreadedServiceClientRuntime, BindingSnapshot, RuntimeSnapshot

WORKSPACE = Path(__file__).resolve().parents[3]
ACCOUNT = 'synthetic-account'
STRATEGY = 'synthetic-strategy'
PARENT = 'synthetic-parent'
REGISTER_ID = 'synthetic-register'
CANCEL_ID = 'synthetic-cancel'


pytestmark = pytest.mark.skip(reason=(
    "RETIRED iteration-65 prototype: it models the pre-continuity SDK parent-origin "
    "contract that no longer exists. ParentAuthority keeps Gateway registration local "
    "(PENDING) while _gateway_continuity_proven() is False, so the modeled dispatch "
    "and race are unreachable; the SDK's own iter65 origin/vertical tests cover the "
    "current seam. Rebuilding it here would fabricate an unproven continuity anchor."
))


@pytest.fixture(scope='module', autouse=True)
def isolated_sources():
    yield
    wrong = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'backtrader' or name.startswith(('backtrader.', 'bt_api_py', 'bt_api_')):
            source = getattr(module, '__file__', None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                wrong[name] = source
    assert not wrong, f'non-worktree modules: {wrong}'


@contextmanager
def synthetic_fence():
    # Test-only scope: no production authentication or account grant is claimed.
    yield


class GatewayThread:
    """Hold the real Gateway guard and journal exclusively on their owner thread."""
    def __init__(self, directory):
        self.directory = directory
        self.queue = Queue()
        self.ready = Future()
        self.thread = threading.Thread(target=self.run, name='synthetic-gateway-owner')
        self.thread.start()
        self.ready.result(timeout=10)

    def run(self):
        guard = None
        try:
            guard_dir = self.directory / 'guard'
            guard_dir.mkdir()
            guard = LocalAccountSessionGuard(guard_dir, ACCOUNT, 'synthetic-owner')
            generation = guard.acquire()
            journal = GatewayDirectCommandJournal.create(self.directory / 'gateway.sqlite', ACCOUNT, generation=generation)
            journal.enable_controls(guard)
            journal.enable_strategy_ledger(guard)
            journal.enable_account_extensions(guard)
            journal.enable_parent_authority(guard)
            authority = GatewayParentAuthority(journal, guard, now_ns=time.time_ns,
                trading_day=lambda: '20261109', transfer_completed=lambda db, spec: '0', same_day_only=True)
            self.ready.set_result(True)
            while True:
                operation, args, result = self.queue.get()
                if operation == 'close':
                    result.set_result(None)
                    break
                try:
                    access = dict(principal='synthetic-exec', actor_ref='synthetic-actor',
                                  fence=synthetic_fence, recheck=lambda: True)
                    if operation == REGISTER:
                        value = authority.register_parent(args['spec'], **access)
                    elif operation == CANCEL:
                        value = authority.cancel_parent(args['account_scope'], args['strategy_scope'],
                            args['parent_ref'], args['registration_operation_id'], args['cancel_operation_id'],
                            args['expected_version'], **access)
                    elif operation == OPERATION:
                        value = authority.query_operation(args['account_scope'], args['strategy_scope'],
                            args['parent_ref'], args['operation_id'], **access)
                    elif operation == QUERY:
                        value = authority.query_parent(args['account_scope'], args['strategy_scope'],
                            args['parent_ref'], args['registration_operation_id'], **access)
                    else:
                        raise ValueError('unexpected synthetic operation')
                    result.set_result(value)
                except Exception as error:
                    result.set_exception(error)
        except BaseException as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            else:
                raise
        finally:
            if guard is not None:
                guard.release()

    def call(self, operation, args):
        result = Future()
        self.queue.put((operation, args, result))
        return result.result(timeout=10)

    def close(self):
        try:
            self.call('close', {})
        finally:
            self.thread.join(timeout=10)
        assert not self.thread.is_alive()


@pytest.fixture
def system(tmp_path, monkeypatch):
    gateway = GatewayThread(tmp_path)
    store = None
    try:
        scope = ExecutionScope('SYNTHETIC', 'test', ACCOUNT, STRATEGY, '20261109')
        store = SqliteExecutionStore(tmp_path / 'execution.sqlite')
        lease = store.acquire_or_renew_lease(scope, 'synthetic-writer', ttl_ns=300_000_000_000)
        authority = ParentAuthority(store, scope, lease, admission=lambda action, spec: True)
        identity = WireIdentity(WireRole.SERVICE, 'synthetic-exec', 'synthetic-actor')
        wire_scope = WireScope('synthetic-domain', account_ref=ACCOUNT, strategy_ref=STRATEGY, run_id='synthetic-run')
        route = GatewayDelegateRoute('upstream.direct_write', 'synthetic-gateway', 'instance', 'scope', wire_scope, identity)
        runtime = ThreadedServiceClientRuntime(lambda: None)
        operations = frozenset({REGISTER, CANCEL, OPERATION, QUERY})
        binding = BindingSnapshot('synthetic-registration', 'synthetic-epoch', True, route.mount,
            route.service_id, route.instance_id, route.scope_ref, wire_scope, operations, True)
        snapshot = RuntimeSnapshot('running', True, True, None, (binding,), 0, 0, identity, 'synthetic-run')
        monkeypatch.setattr(runtime, 'status', lambda: snapshot)
        port = SyntheticTransport(gateway)
        monkeypatch.setattr(runtime, 'call', port.call)
        client = GatewayParentServiceClient(runtime, route=route, host=authority)
        authority.bind_gateway(client)
        parent = dict(parent_ref=PARENT, registration_operation_id=REGISTER_ID, risk_operation_id='synthetic-risk',
            account_scope=ACCOUNT, strategy_scope=STRATEGY, execution_domain_ref='synthetic-domain',
            instrument=MarketInstrumentKey('ctp', 'SHFE', 'synthetic', 'future', 'rb2601', 'rb2601').to_dict(),
            quantity='10', quantity_unit='lots', side='buy', offset='open', limit_price='100',
            creation_trading_day='20261109', allowed_trading_days=['20261109'],
            expires_at_ns=time.time_ns() + 60_000_000_000, grant_revision='v1', plan_digest='a' * 64,
            plan_version='v1', target_position_ref=None, risk_selected=False, time_in_force='GTD')
        authority.accept(parent)
        yield authority, client, port, gateway, parent
    finally:
        if store is not None:
            store.close()
        gateway.close()


class SyntheticTransport:
    """Control message delivery, not a real service registry or authenticated RPC."""
    def __init__(self, gateway):
        self.gateway = gateway
        self.hold_registration = False
        self.held = None
        self.calls = []
        self.sent = threading.Event()

    def call(self, mount, operation, args, **kwargs):
        self.calls.append(operation)
        if operation == REGISTER and self.hold_registration:
            assert self.held is None
            self.held = dict(args)
            self.sent.set()  # synthetic transport accepted the request, not Gateway
            raise TimeoutError('synthetic delayed delivery')
        result = self.gateway.call(operation, args)
        return dict(status='OBSERVED', schema_version=1, operation=operation, result=result)

    def deliver_held(self):
        assert self.sent.wait(timeout=10) and self.held is not None
        args, self.held = self.held, None
        return self.gateway.call(REGISTER, args)


def query_args():
    return dict(account_scope=ACCOUNT, strategy_scope=STRATEGY, parent_ref=PARENT,
                registration_operation_id=REGISTER_ID)


def test_delayed_register_after_cancel_and_negative_queries(system):
    authority, client, port, gateway, spec = system
    port.hold_registration = True
    assert authority.register(PARENT)['gateway_state'] == 'UNKNOWN'
    assert port.sent.wait(timeout=10)
    # Querying this owner's current journal finds nothing; the held request can
    # still arrive, so NOT_FOUND does not prove no future registration.
    with pytest.raises(GatewayParentError, match='NOT_FOUND'):
        gateway.call(OPERATION, dict(query_args(), operation_id=REGISTER_ID))
    assert authority.cancel(PARENT, CANCEL_ID, 1)['cancel_state'] == 'UNKNOWN'
    with pytest.raises(GatewayParentError, match='NOT_FOUND'):
        gateway.call(OPERATION, dict(query_args(), operation_id=CANCEL_ID))
    assert authority.reconcile(PARENT, 'gateway')['gateway_state'] == 'UNKNOWN'
    assert authority.reconcile_cancel(PARENT)['cancel_state'] == 'UNKNOWN'
    assert port.deliver_held()['state'] == 'ACTIVE'
    assert gateway.call(OPERATION, dict(query_args(), operation_id=REGISTER_ID))['result']['state'] == 'ACTIVE'
    assert authority.reconcile(PARENT, 'gateway')['gateway_state'] == 'ACCEPTED'
    assert authority.reconcile_cancel(PARENT)['cancel_state'] == 'UNKNOWN'
    assert authority.cancel(PARENT, CANCEL_ID, 1)['cancel_state'] == 'UNKNOWN'
    assert port.calls.count(REGISTER) == 1 and port.calls.count(CANCEL) == 1
    assert client.query_parent(spec)['state'] == 'ACTIVE'


def test_register_then_cancel_then_late_duplicate_register(system):
    authority, client, port, gateway, spec = system
    assert authority.register(PARENT)['gateway_state'] == 'ACCEPTED'
    assert client.query_operation(spec, REGISTER_ID)['result']['state'] == 'ACTIVE'
    assert authority.cancel(PARENT, CANCEL_ID, 1)['cancel_state'] == 'REQUESTED'
    assert client.query_operation(spec, CANCEL_ID)['result']['state'] == 'CANCEL_REQUESTED'
    assert client.query_parent(spec)['state'] == 'CANCEL_REQUESTED'
    # A delayed duplicate arrives at the actual Gateway owner after cancellation.
    # The operation receipt remains the original ACTIVE registration result,
    # while registration replay returns the current CANCEL_REQUESTED row.
    gateway_spec = {k: v for k, v in spec.items() if k not in {'risk_selected', 'risk_operation_id'}}
    assert gateway.call(REGISTER, {'spec': gateway_spec})['state'] == 'CANCEL_REQUESTED'
    assert client.query_operation(spec, REGISTER_ID)['result']['state'] == 'ACTIVE'
    assert client.query_parent(spec)['state'] == 'CANCEL_REQUESTED'
    assert port.calls.count(REGISTER) == 1 and port.calls.count(CANCEL) == 1


def test_cancel_between_local_claim_and_sdk_dispatch_blocks_unsent_registration(system):
    authority, client, port, gateway, _ = system
    # Explicitly split the existing register method at its private durable
    # claim to model this one ordering; do not bypass the SDK dispatch fence.
    claimed = authority._claim(PARENT, 'gateway_state', lambda row: row['risk_state'] == 'NOT_SELECTED')
    assert authority.cancel(PARENT, CANCEL_ID, 1)['cancel_state'] == 'UNKNOWN'
    assert client.register_parent(claimed, REGISTER_ID) is None
    assert REGISTER not in port.calls and port.calls.count(CANCEL) == 1
    with pytest.raises(GatewayParentError, match='NOT_FOUND'):
        gateway.call(OPERATION, dict(query_args(), operation_id=REGISTER_ID))
    assert authority.get(PARENT)['gateway_state'] == 'UNKNOWN'
