"""Root-only credential-free real Windows Pipe gate; no worker process/network."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import multiprocessing
import socket
import stat
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--expected-owner-sha256', required=True)
options = parser.parse_args()
root = Path('D:/source_code/backtrader')
suite = root / 'examples/000_live_certification/binance_penetration'
owner_path = suite / '_certification/th01_root_protected_owner_r1.py'
info = owner_path.lstat()
assert stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
assert 0 < info.st_size < 200_000
data = owner_path.read_bytes()
assert hashlib.sha256(data).hexdigest() == options.expected_owner_sha256
sys.path.insert(0, str(suite))
source = importlib.import_module('_certification.th01_root_protected_owner_r1')
assert Path(source.__file__).resolve() == owner_path.resolve()
assert source._ACTIVE_ROOT_FIXED_WORKERS == []
real_context = multiprocessing.get_context('spawn')
original_get_context = source.multiprocessing.get_context
original_connect = socket.socket.connect
original_create_connection = socket.create_connection
connections = []
processes = []
current_mode = None

def denied_network(*_args, **_kwargs):
    raise AssertionError('network_forbidden_in_public_pipe_gate')

class Writer:
    def __init__(self, connection):
        self.connection = connection
        self.close_calls = 0
    def send(self, value):
        self.connection.send(value)
    def close(self):
        self.close_calls += 1
        if current_mode != 'no_eof' or self.close_calls >= 2:
            self.connection.close()

class Process:
    def __init__(self, *, target, args, name, daemon):
        assert target is source._root_fixed_signed_get_worker
        assert name == 'th01-fixed-signed-read' and daemon is True
        self.args = args
        self.exitcode = 0
        self.closed = False
        processes.append(self)
    def start(self):
        writer, resource, planned, api_key, secret, _, _ = self.args
        assert resource == 'account_configuration' and planned == {}
        assert api_key == 'PUBLIC_SYNTHETIC_KEY' and secret == 'PUBLIC_SYNTHETIC_SECRET'
        now_ms = int(time.time() * 1000)
        frame = (200, b'[]', True, None,
                 {'recvWindow': 5000, 'timestamp': now_ms}, now_ms, now_ms)
        writer.send(frame)
        if current_mode == 'second_frame':
            writer.send(('public-extra-frame',))
        if current_mode != 'no_eof':
            writer.close()
    def is_alive(self):
        assert not self.closed, 'closed_process_revisited'
        return False
    def join(self, timeout):
        assert timeout == 1.0 and not self.closed
    def close(self):
        assert not self.closed
        self.closed = True
    def terminate(self):
        raise AssertionError('fake_process_must_not_be_terminated')

class Context:
    def Pipe(self, duplex):
        assert duplex is False
        parent, child = real_context.Pipe(duplex=False)
        connections.extend((parent, child))
        return parent, Writer(child)
    Process = Process

def get_context(kind):
    assert kind == 'spawn'
    return Context()

checks = {}
try:
    source.multiprocessing.get_context = get_context
    socket.socket.connect = denied_network
    socket.create_connection = denied_network
    for current_mode in ('valid', 'second_frame', 'no_eof'):
        start_ms = int(time.time() * 1000) - 60_000
        try:
            outcome = source._run_root_fixed_signed_get(
                'account_configuration', {}, 'PUBLIC_SYNTHETIC_KEY',
                'PUBLIC_SYNTHETIC_SECRET', start_ms, time.monotonic() + 7.0)
            assert current_mode == 'valid'
            checks[current_mode] = (
                outcome.status == 200 and outcome.complete is True
                and outcome.reason is None and outcome.pipe_eof is True
                and outcome.worker_exit_code == 0 and not outcome.forced_shutdown
            )
        except source.RootTH01AccountWindowBlocked as exc:
            expected = {'second_frame': 'fixed_get_multiple_frames',
                        'no_eof': 'fixed_get_response_pipe_uncertain'}
            assert current_mode in expected and exc.code == expected[current_mode]
            checks[current_mode] = True
        assert source._ACTIVE_ROOT_FIXED_WORKERS == []
        assert all(item.closed for item in connections)
        assert all(item.closed for item in processes)
finally:
    source.multiprocessing.get_context = original_get_context
    socket.socket.connect = original_connect
    socket.create_connection = original_create_connection
    for connection in connections:
        connection.close()
assert all(checks.values()) and len(checks) == 3
assert hashlib.sha256(owner_path.read_bytes()).hexdigest() == options.expected_owner_sha256
print(json.dumps({'schema': 'iteration41.binance.th01.r8.root-real-pipe-gate.v1',
                  'checks': checks, 'all_connections_closed': all(item.closed for item in connections),
                  'all_fake_processes_closed': all(item.closed for item in processes),
                  'active_workers_zero': source._ACTIVE_ROOT_FIXED_WORKERS == [],
                  'source_prepost_pin_match': True, 'private_input_read': False,
                  'provider_call': False, 'process_spawned': False,
                  'evidence_level': 'ROOT_LOCAL_CREDENTIAL_FREE_PIPE_ONLY'}, sort_keys=True))
