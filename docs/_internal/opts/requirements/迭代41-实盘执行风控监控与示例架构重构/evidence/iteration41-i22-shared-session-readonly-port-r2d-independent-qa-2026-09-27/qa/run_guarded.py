import builtins, io, json, os, socket, sys
from pathlib import Path
root = Path(r'D:\temp\iteration41-r2d-shared-session-readonly-port-20260927')
out = Path(r'D:\temp\iteration41-r2d-independent-audit-20260927')
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['BT_API_PY_LIGHT_IMPORT'] = '1'
os.chdir(root)
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
import pytest
attempts = {'sdk': [], 'network': [], 'private': []}
orig_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    prefixes = ('bt_api_py', 'bt_api_ctp', '_ctp', 'ctp_wrap', 'thostmduserapi', 'thosttraderapi')
    if any(name == p or name.startswith(p + '.') for p in prefixes):
        attempts['sdk'].append(name)
        raise AssertionError('blocked SDK/native import')
    return orig_import(name, globals, locals, fromlist, level)
def check_path(value):
    try: path = os.fspath(value)
    except TypeError: return
    if isinstance(path, bytes): path = os.fsdecode(path)
    folded = path.replace('/', '\\').lower()
    if 'runtime-ctp-private' in folded or '013_3_sa_midfreq_simnow\\.env' in folded:
        attempts['private'].append(path)
        raise AssertionError('blocked private-config access')
orig_builtin_open, orig_io_open, orig_os_open = builtins.open, io.open, os.open
def guarded_builtin_open(file, *args, **kwargs): check_path(file); return orig_builtin_open(file, *args, **kwargs)
def guarded_io_open(file, *args, **kwargs): check_path(file); return orig_io_open(file, *args, **kwargs)
def guarded_os_open(file, *args, **kwargs): check_path(file); return orig_os_open(file, *args, **kwargs)
def blocked_network(*args, **kwargs):
    attempts['network'].append('socket')
    raise AssertionError('blocked network access')
builtins.__import__ = guarded_import
builtins.open, io.open, os.open = guarded_builtin_open, guarded_io_open, guarded_os_open
socket.socket.connect = blocked_network
socket.socket.connect_ex = blocked_network
socket.create_connection = blocked_network
socket.getaddrinfo = blocked_network
args = ['-p','no:asyncio','-p','no:cacheprovider',
 'tests/unit/stores/test_btapistore_iteration22.py::test_empty_incomplete_query_is_not_interpreted_as_zero_records',
 'tests/unit/stores/test_btapistore_iteration22.py::test_query_request_type_mismatch_fails_closed',
 'tests/unit/stores/test_btapistore_iteration22.py::test_preflight_rejects_trade_rows_outside_the_requested_scope',
 'tests/unit/stores/test_ctp_shared_session_read_port.py','-q','--tb=short',
 '--basetemp',str(out/'pytest-basetemp'),'--junitxml',str(out/'candidate-focused.junit.xml')]
code = int(pytest.main(args))
native = sorted(n for n in sys.modules if n.startswith(('bt_api_py','bt_api_ctp','_ctp','ctp_wrap','thostmduserapi','thosttraderapi')))
print(json.dumps({'pytest_exit_code':code,'blocked_sdk_import_attempts':attempts['sdk'],'sdk_native_modules_loaded':native,'network_attempts':attempts['network'],'private_path_attempts':attempts['private'],'scope':args},indent=2))
if attempts['sdk'] or native or attempts['network'] or attempts['private']: raise SystemExit(2)
raise SystemExit(code)
