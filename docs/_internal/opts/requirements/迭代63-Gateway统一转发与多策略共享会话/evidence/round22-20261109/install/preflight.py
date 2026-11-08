import os,socket,sys
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');sys.path[:0]=[str(T/'install'),str(T/'bootstrap')]
os.environ['R22_CTP_STRUCTS']='0'
from origin_guard import audit,install as install_origin
from offline_guard import install as install_offline
install_origin('r22-preflight');install_offline()
assert not any(n.startswith('bt_api_ctp') for n in sys.modules)
try: socket.socket().connect(('203.0.113.1',1))
except PermissionError as error: assert str(error)=='R22_OFFLINE_NON_LOOPBACK_BLOCKED'
else: raise AssertionError('nonloopback not blocked')
assert not any(n.startswith('bt_api_ctp') for n in sys.modules)
assert audit()
print('NONLOOPBACK_BLOCKED_AND_CTP_NOT_IMPORTED')
