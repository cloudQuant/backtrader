"""65.01 local two-process FAKE lease diagnostic, using synthetic admission.

This is not CTP, account takeover, a service flow lock, or multi-host evidence.
Sharing a writer ID in this fixture does not establish a production lock defect.
"""

import json
import os
from pathlib import Path
import selectors
import signal
import sqlite3
import subprocess
import sys
import tempfile
import textwrap


CHILD = textwrap.dedent('''
    import json
    import os
    from pathlib import Path
    import sys
    import time

    def forbidden(name):
        return (name in {'socket', '_socket', 'bt_api_ctp'} or
                name.startswith('bt_api_ctp.') or '_ctp' in name.split('.'))

    assert not [name for name in sys.modules if forbidden(name)]

    class BlockNetworkAndCtp:
        def find_spec(self, fullname, path=None, target=None):
            if forbidden(fullname):
                raise ModuleNotFoundError('FAKE diagnostic blocks import: ' + fullname)
            return None

    sys.meta_path.insert(0, BlockNetworkAndCtp())

    import bt_api_base
    import bt_api_execution
    from bt_api_base.market_protocol import MarketInstrumentKey
    from bt_api_execution.contracts import ExecutionScope
    from bt_api_execution.errors import WriterLeaseUnavailableError
    from bt_api_execution.parent_authority import ParentAuthority
    from bt_api_execution.store import SqliteExecutionStore

    workspace = Path(sys.argv[1]).resolve()
    for name, module in tuple(sys.modules.items()):
        if name == 'bt_api' or name.startswith(('bt_api.', 'bt_api_')):
            paths = ([module.__file__] if getattr(module, '__file__', None) else [])
            paths.extend(getattr(module, '__path__', ()))
            assert all(Path(path).resolve().is_relative_to(workspace) for path in paths), name
    assert Path(bt_api_base.__file__).resolve().is_relative_to(workspace)
    assert Path(bt_api_execution.__file__).resolve().is_relative_to(workspace)
    assert not [name for name in sys.modules if forbidden(name)]
    assert os.getpid() != int(sys.argv[3])

    scope = ExecutionScope('fake', 'offline', 'synthetic-account', 'synthetic-strategy', '20261109')
    store = SqliteExecutionStore(sys.argv[2])
    lease = None
    authority = None

    def spec(parent):
        instrument = MarketInstrumentKey('fake', 'SYNTHETIC', 'synthetic', 'future', 'rb', 'rb')
        return {
            'parent_ref': parent, 'registration_operation_id': 'register-' + parent,
            'risk_operation_id': 'risk-' + parent, 'account_scope': scope.account_ref,
            'strategy_scope': scope.strategy_id, 'execution_domain_ref': 'synthetic-domain',
            'instrument': instrument.to_dict(), 'quantity': '5', 'quantity_unit': 'lots',
            'side': 'buy', 'offset': 'open', 'limit_price': '10',
            'creation_trading_day': '20261109', 'allowed_trading_days': ['20261109'],
            'expires_at_ns': time.time_ns() + 60_000_000_000,
            'grant_revision': 'synthetic-grant', 'plan_digest': 'a' * 64,
            'plan_version': 'v1', 'target_position_ref': None,
            'risk_selected': False, 'time_in_force': 'DAY',
        }

    def reply(**value):
        print(json.dumps(value), flush=True)

    reply(pid=os.getpid(), base=str(Path(bt_api_base.__file__).resolve()),
          execution=str(Path(bt_api_execution.__file__).resolve()),
          executable=str(Path(sys.executable).resolve()))
    try:
        for line in sys.stdin:
            command = json.loads(line)
            op = command['op']
            try:
                if op == 'acquire':
                    lease = store.acquire_or_renew_lease(scope, command['owner'], ttl_ns=300_000_000_000)
                    authority = ParentAuthority(store, scope, lease, admission=lambda action, value: True)
                    reply(status='acquired', token=lease.fencing_token, owner=lease.owner_id)
                elif op == 'write':
                    row = authority.accept(spec(command['parent']))
                    reply(status='written', parent=row['parent_id'], gateway_state=row['gateway_state'])
                elif op == 'release':
                    released = store.release_lease(scope, lease.owner_id, fencing_token=lease.fencing_token)
                    reply(status='released', released=released)
                elif op == 'quit':
                    reply(status='bye')
                    break
                else:
                    raise AssertionError('unknown command')
            except WriterLeaseUnavailableError:
                reply(status='lease_unavailable')
    finally:
        store.close()
''')


class Child:
    def __init__(self, workspace, database, environment):
        self.stderr = tempfile.TemporaryFile(mode='w+t')
        self.process = subprocess.Popen(
            ['/Users/yunjinqi/opt/anaconda3/bin/conda', 'run', '--no-capture-output',
             '-n', 'base', 'python', '-u', '-c', CHILD, str(workspace), str(database), str(os.getpid())],
            cwd=workspace / 'bt_api_py', env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1, start_new_session=True,
        )

    def receive(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            ready = selector.select(timeout=30)
        if not ready:
            raise AssertionError('child response timed out')
        line = self.process.stdout.readline()
        if not line:
            self.stderr.seek(0)
            raise AssertionError('child exited without response: ' + self.stderr.read())
        return json.loads(line)

    def request(self, op, **values):
        assert self.process.poll() is None
        self.process.stdin.write(json.dumps({'op': op, **values}) + '\n')
        self.process.stdin.flush()
        return self.receive()

    def cleanup(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()


def test_fake_parent_lease_in_two_live_processes(tmp_path):
    workspace = Path(__file__).resolve().parents[3]
    assert workspace.name == 'wt-iter65'
    base_python = Path('/Users/yunjinqi/opt/anaconda3/bin/python').resolve()
    assert Path(sys.executable).resolve() == base_python
    sdk = workspace / 'bt_api_py'
    paths = [sdk, sdk / 'bt_api/bt_api_base/src', sdk / 'bt_api/bt_api_execution/src']
    assert all(path.is_dir() for path in paths)
    env = {'PATH': str(base_python.parent) + ':/usr/bin:/bin', 'PYTHONPATH': os.pathsep.join(map(str, paths)),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    database = tmp_path / 'fake-process.sqlite'
    assert not database.exists()
    children = []
    try:
        a = Child(workspace, database, env)
        children.append(a)
        a_info = a.receive()
        b = Child(workspace, database, env)
        children.append(b)
        b_info = b.receive()
        assert len({os.getpid(), a_info['pid'], b_info['pid']}) == 3
        for child, info in ((a, a_info), (b, b_info)):
            assert os.getpgid(info['pid']) == child.process.pid
            assert Path(info['executable']) == base_python
            assert all(Path(info[key]).is_relative_to(workspace) for key in ('base', 'execution'))

        first = a.request('acquire', owner='writer-same')
        assert first['status'] == 'acquired'
        assert a.request('write', parent='parent-A') == {
            'status': 'written', 'parent': 'parent-A', 'gateway_state': 'PENDING'}
        assert a.process.poll() is None and b.process.poll() is None
        assert b.request('acquire', owner='writer-different') == {'status': 'lease_unavailable'}
        second = b.request('acquire', owner='writer-same')
        assert second == {'status': 'acquired', 'token': first['token'], 'owner': 'writer-same'}
        assert b.request('write', parent='parent-B') == {
            'status': 'written', 'parent': 'parent-B', 'gateway_state': 'PENDING'}
        assert a.request('release') == {'status': 'released', 'released': True}
        newer = a.request('acquire', owner='writer-new')
        assert newer['status'] == 'acquired' and newer['owner'] == 'writer-new'
        assert newer['token'] > first['token']
        assert b.request('write', parent='parent-C') == {'status': 'lease_unavailable'}
        assert a.request('write', parent='parent-D') == {
            'status': 'written', 'parent': 'parent-D', 'gateway_state': 'PENDING'}
        assert all(child.process.poll() is None for child in children)
        for child in children:
            assert child.request('quit') == {'status': 'bye'}
            assert child.process.wait(timeout=10) == 0

        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
            parents = connection.execute(
                'SELECT parent_id, gateway_state FROM execution_parent_records ORDER BY parent_id'
            ).fetchall()
            leases = connection.execute(
                'SELECT owner_id, fencing_token FROM execution_writer_leases'
            ).fetchall()
        assert parents == [('parent-A', 'PENDING'), ('parent-B', 'PENDING'), ('parent-D', 'PENDING')]
        assert leases == [('writer-new', newer['token'])]
    finally:
        for child in children:
            child.cleanup()
