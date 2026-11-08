"""Exercise construction in a new isolated interpreter using installed SDK/Base."""
import hashlib
import importlib.util
import os
import socket
import sys
import threading
from pathlib import Path

root = Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
target = (root/'install/src').resolve()
sys.path[:0] = [str(target), str(root/'bootstrap')]
os.environ['R18_ORIGIN_RUN'] = 'installed-cold-client-probe'
from origin_guard import install, audit
from offline_guard import install as offline
install('installed-cold-client-probe')
offline()
forbidden = ('zmq','bt_api_transport_zmq','bt_api_gateway','bt_api_ctp','bt_api_risk','bt_api_execution')
def clean():
    assert not [n for n in sys.modules if any(n == p or n.startswith(p+'.') for p in forbidden)]
clean()
helper = root/'sdk-tests/tests/unit/test_iter63_gateway_strategy_client.py'
spec = importlib.util.spec_from_file_location('public_session_inputs', helper)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
clean()
assert Path(sys.modules['bt_api_py.gateway_strategy_client'].__file__).resolve().is_relative_to(target)
before = {t.ident for t in threading.enumerate()}
original = socket.socket
def reject_socket(*args, **kwargs):
    raise AssertionError('unexpected socket creation during constructor/close')
socket.socket = reject_socket
try:
    session = m.GatewayStrategyClientSession(**m.parts())
    assert session.status().state == 'new' and not session.status().thread_alive
    assert {t.ident for t in threading.enumerate()} == before
    clean()
    assert session.close().state == 'closed'
    assert {t.ident for t in threading.enumerate()} == before
    clean()
finally:
    socket.socket = original
assert audit('installed-cold-client-origin-audit')
print('PASS installed constructor/close: no socket creation, no thread, no forbidden package import')
print('HELPER_SHA256', hashlib.sha256(helper.read_bytes()).hexdigest())
print('INSTALLED_MODULE_SHA256', hashlib.sha256(Path(sys.modules['bt_api_py.gateway_strategy_client'].__file__).read_bytes()).hexdigest())
