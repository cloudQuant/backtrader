import hashlib, os, sys
from pathlib import Path
root=Path(__file__).resolve().parent
target=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final/install/src').resolve()
sys.path[:0]=[str(target),str(root)]
os.environ['R09_ORIGIN_RUN']='r10_baseline'
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
from origin_guard import install, audit
install('r10-baseline')
from fake_native import install as no_native
no_native()
import socket
def forbidden(*args,**kwargs): raise RuntimeError('NETWORK_DISABLED_FOR_SYNTHETIC_TEST')
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
import bt_api_py, bt_api_base, bt_api_ctp, bt_api_gateway
import bt_api_py.order_correlation_issuer, bt_api_ctp.account_provider, bt_api_ctp.query, bt_api_gateway.account_session_worker
for name in ('bt_api_py','bt_api_base','bt_api_ctp','bt_api_gateway','bt_api_py.order_correlation_issuer','bt_api_ctp.account_provider','bt_api_ctp.query','bt_api_gateway.account_session_worker'):
 m=sys.modules[name]; p=Path(m.__file__).resolve(); assert p.is_relative_to(target); print('MODULE',name,p,flush=True)
test=root/'test_iter60_ctp_gateway_execution_events.py'
print('TEST_SHA256',hashlib.sha256(test.read_bytes()).hexdigest(),flush=True)
print('CTP_NATIVE_AND_NETWORK_DISABLED',flush=True)
import pytest
code=pytest.main(['-q','--import-mode=importlib','-p','no:cacheprovider','--basetemp='+str(root/'pytest-tmp'),str(test)])
assert 'bt_api_ctp.ctp._ctp' not in sys.modules
assert audit()
print('ORIGIN_AUDIT_OK; CTP_NATIVE_NOT_LOADED',flush=True)
raise SystemExit(code)
