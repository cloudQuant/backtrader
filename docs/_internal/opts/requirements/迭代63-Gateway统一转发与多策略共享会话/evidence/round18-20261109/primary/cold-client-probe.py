import sys, threading, importlib.util, hashlib
from pathlib import Path
sdk=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
root=Path('/tmp/iter63-r18-primary')
sys.path[:0]=[str(root/'bootstrap'),str(sdk/'bt_api/bt_api_base/src'),str(sdk)]
from origin_guard import install, audit
from offline_guard import install as offline
install('cold-client-probe');offline()
forbidden=('zmq','bt_api_transport_zmq','bt_api_gateway','bt_api_ctp','bt_api_risk','bt_api_execution')
assert not any(any(n==p or n.startswith(p+'.') for p in forbidden) for n in sys.modules)
spec=importlib.util.spec_from_file_location('public_session_inputs',sdk/'tests/unit/test_iter63_gateway_strategy_client.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
before={t.ident for t in threading.enumerate()}
session=m.GatewayStrategyClientSession(**m.parts())
assert session.status().state=='new' and not session.status().thread_alive
assert {t.ident for t in threading.enumerate()}==before
assert not any(any(n==p or n.startswith(p+'.') for p in forbidden) for n in sys.modules)
assert session.close().state=='closed'
assert audit('cold-client-origin-audit')
print('PASS: constructor starts no thread and imports no provider, Gateway, transport, Risk or Execution package')
print('module_sha256',hashlib.sha256(Path(sys.modules['bt_api_py.gateway_strategy_client'].__file__).read_bytes()).hexdigest())
