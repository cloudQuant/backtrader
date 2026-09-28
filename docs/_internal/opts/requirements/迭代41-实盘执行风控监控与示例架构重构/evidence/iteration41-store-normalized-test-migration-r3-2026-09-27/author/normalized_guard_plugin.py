from __future__ import annotations
import importlib.abc, ipaddress, json, os, socket, sys
from pathlib import Path
REPORT=Path(os.environ.get('NORM_GUARD_REPORT',r'D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\guard-report.json'))
PREFIXES=('bt_api_ctp','bt_api_py','bt_api_base','vnpy','ctp')
imports=[]; blocked_sockets=[]; local_loopback=[]
_ORIGINAL_CONNECT=socket.socket.connect
_ORIGINAL_CONNECT_EX=socket.socket.connect_ex
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in PREFIXES):
            imports.append(fullname)
            raise ModuleNotFoundError(f'provider/native import blocked: {fullname}')
        return None
def _is_loopback_address(args):
    if not args:
        return False
    address=args[1] if len(args) > 1 and isinstance(args[0], socket.socket) else args[0]
    if not isinstance(address,tuple) or not address:
        return False
    host=address[0]
    try:
        return ipaddress.ip_address(host.split('%',1)[0]).is_loopback
    except (ValueError,AttributeError,TypeError):
        return False
def pytest_configure(config):
    sys.meta_path.insert(0,Blocker())
    def blocked(label):
        def call(*args,**kwargs):
            if label in {'socket.connect','socket.connect_ex'} and _is_loopback_address(args):
                local_loopback.append(label)
                original=_ORIGINAL_CONNECT if label.endswith('connect') else _ORIGINAL_CONNECT_EX
                return original(*args,**kwargs)
            blocked_sockets.append({'operation':label,'address':repr(args[1] if len(args) > 1 and isinstance(args[0], socket.socket) else (args[0] if args else None))})
            raise RuntimeError(f'non-loopback network/socket operation blocked: {label}')
        return call
    socket.socket.connect=blocked('socket.connect')
    socket.socket.connect_ex=blocked('socket.connect_ex')
    socket.create_connection=blocked('socket.create_connection')
def pytest_sessionfinish(session,exitstatus):
    REPORT.write_text(json.dumps({'exitstatus':exitstatus,'blocked_prefixes':PREFIXES,'provider_import_attempts':imports,'blocked_external_socket_attempts':blocked_sockets,'allowed_local_loopback_socketpair_attempts':local_loopback},indent=2),encoding='utf-8')
