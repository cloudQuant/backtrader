"""Verify lazy extension guard without calling a real CTP factory or network."""
import os
import socket
import sys
from pathlib import Path
T = Path('/tmp/iter63-r28-candidate2-20261109-hLnRZEKN')
sys.path[:0] = [str(T/'install/src'), str(T/'bootstrap')]
os.environ['R25_CTP_STRUCTS'] = '1'
os.environ.setdefault('R25_ORIGIN_RUN', 'guard-preflight')
from origin_guard import install as install_origin, audit
from offline_guard import install as install_offline
install_origin('guard-preflight')
install_offline()
assert not any(name.startswith('bt_api_ctp') for name in sys.modules), 'guard eagerly imported CTP'
assert 'zmq' not in sys.modules, 'guard eagerly imported zmq'
import bt_api_py.gateway_direct_client
assert not any(name.startswith('bt_api_ctp') for name in sys.modules), 'SDK client eagerly imported CTP'
from bt_api_ctp.ctp import _ctp
for name in ('CThostFtdcTraderApi_CreateFtdcTraderApi', 'CThostFtdcMdApi_CreateFtdcMdApi'):
    try:
        getattr(_ctp, name)()
    except PermissionError as exc:
        assert str(exc) == 'R25_OFFLINE_CTP_FACTORY_BLOCKED'
    else:
        raise AssertionError('CTP factory was not blocked')
try:
    socket.socket().connect(('203.0.113.1', 1))
except PermissionError as exc:
    assert str(exc) == 'R25_OFFLINE_NON_LOOPBACK_BLOCKED'
else:
    raise AssertionError('non-loopback was not blocked')
assert 'zmq' not in sys.modules, 'guard eagerly imported zmq'
import zmq
context = zmq.Context()
channel = context.socket(zmq.REQ)
try:
    try:
        channel.connect('tcp://203.0.113.1:12345')
    except PermissionError as exc:
        assert str(exc) == 'R25_OFFLINE_NON_LOOPBACK_BLOCKED'
    else:
        raise AssertionError('external zmq endpoint was not blocked')
finally:
    channel.close(linger=0)
    context.term()
assert audit()
print('LAZY_CTP_FACTORY_GUARD_AND_NON_LOOPBACK_BLOCKED')
