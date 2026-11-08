"""Verify source guard stays lazy and blocks a non-loopback socket."""
import os
import socket
import sys
from pathlib import Path
OUT=Path('/tmp/iter63-r17-primary')
SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
os.environ['R17_ORIGIN_RUN']='source-guard-preflight'
os.environ['R17_CTP_STRUCTS']='0'
sys.path[:0]=[str(OUT/'bootstrap'),str(SDK)]
from origin_guard import audit, install as install_origin
from offline_guard import install as install_offline
install_origin('preflight')
install_offline()
assert not any(name.startswith('bt_api_ctp') for name in sys.modules)
assert 'zmq' not in sys.modules
import bt_api_py.gateway_direct_client
assert not any(name.startswith('bt_api_ctp') for name in sys.modules)
try:
    socket.socket().connect(('203.0.113.1', 1))
except PermissionError as exc:
    assert str(exc)=='R17_OFFLINE_NON_LOOPBACK_BLOCKED'
else:
    raise AssertionError('external socket was not blocked')
assert 'zmq' not in sys.modules
import zmq
context = zmq.Context()
channel = context.socket(zmq.REQ)
try:
    try:
        channel.connect('tcp://203.0.113.1:12345')
    except PermissionError as exc:
        assert str(exc)=='R17_OFFLINE_NON_LOOPBACK_BLOCKED'
    else:
        raise AssertionError('external zmq endpoint was not blocked')
finally:
    channel.close(linger=0)
    context.term()
assert audit()
print('SOURCE_GUARD_LAZY_AND_EXTERNAL_NETWORK_BLOCKED')
