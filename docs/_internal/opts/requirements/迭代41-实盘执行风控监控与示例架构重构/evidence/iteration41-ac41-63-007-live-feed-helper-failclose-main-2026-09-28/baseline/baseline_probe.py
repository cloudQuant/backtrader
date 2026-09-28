import builtins
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SUPPORT = ROOT / 'evidence' / 'preimage' / 'ctp_example_support.py'
EVENTS = []

# Fake-only boundary: fail if this probe tries a provider/native import or socket I/O.
_original_import = __import__
def _guarded_import(name, *args, **kwargs):
    prefixes = ('bt_api_py', 'bt_api_ctp', 'bt_api_execution', 'thosttrader', 'thostmduserapi', 'ctpbee', 'ctp_api', '_ctp', 'vnpy_ctp')
    if any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes):
        raise AssertionError('provider/native import blocked: ' + name)
    return _original_import(name, *args, **kwargs)
builtins.__import__ = _guarded_import

_original_open = builtins.open
def _guarded_open(file, *args, **kwargs):
    try:
        name = Path(os.fsdecode(os.fspath(file))).name.casefold()
    except (TypeError, ValueError, OSError):
        name = ''
    if name == '.env':
        raise AssertionError('.env access blocked')
    return _original_open(file, *args, **kwargs)
builtins.open = _guarded_open

def _deny(*args, **kwargs):
    raise AssertionError('network call blocked')
socket.getaddrinfo = _deny
socket.create_connection = _deny
for _name in ('connect', 'connect_ex', 'send', 'sendall', 'sendto', 'bind', 'listen', 'accept', 'sendfile'):
    setattr(socket.socket, _name, _deny)

import backtrader  # noqa: F401

def _deny_environment(*args, **kwargs):
    raise AssertionError('support helper read process environment')
os.getenv = _deny_environment

spec = importlib.util.spec_from_file_location('ac41_63_007_baseline_support', SUPPORT)
assert spec is not None and spec.loader is not None
support = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = support
spec.loader.exec_module(support)

class FakeStore:
    def start(self, data=None, broker=None):
        EVENTS.append('store.start')
    def register(self, data):
        EVENTS.append('store.register')
    def fetch_history(self, symbol, **kwargs):
        EVENTS.append('store.fetch_history')
        return []
    def subscribe(self, symbol):
        EVENTS.append('store.subscribe')

class FakeCerebro:
    def adddata(self, data, name=None):
        EVENTS.append('cerebro.adddata')

feeds = support.add_live_feeds(
    FakeCerebro(),
    FakeStore(),
    {'symbols': ['rb2701'], 'feed': {'backfill_start': True}},
)
EVENTS.insert(0, 'helper.returned_feed')
feeds[0].start()
result = {'status': 'FAKE_ONLY_BASELINE_REPRODUCED', 'events': EVENTS}
serialized = json.dumps(result, sort_keys=True)
(ROOT / 'evidence' / 'baseline_probe_result.json').write_text(
    serialized + '\n', encoding='utf-8'
)
print(serialized)



