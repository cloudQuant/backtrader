import importlib.abc
import os
import socket
import sys
import types

root, mode, basetemp = sys.argv[1:]
os.chdir(root)
sys.path[:0] = [root, os.path.join(root, 'tests', 'unit'), '/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_ctp/tests']
sys.dont_write_bytecode = True
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'

class NativeBlocker(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.hits = []
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('bt_api_ctp.ctp._ctp', '_ctp'):
            self.hits.append(fullname)
            raise ModuleNotFoundError('native module disabled by isolated test harness', name=fullname)
        return None

blocker = NativeBlocker()
sys.meta_path.insert(0, blocker)

def no_network(*args, **kwargs):
    raise RuntimeError('network disabled by isolated test harness')
socket.socket.connect = no_network
socket.create_connection = no_network

fake = None
if mode == 'synthetic_native':
    class SyntheticNative(types.ModuleType):
        def __getattr__(self, name):
            if name == '__all__':
                return []
            if name.startswith('__'):
                raise AttributeError(name)
            if name.startswith('THOST_'):
                return name
            return lambda *args, **kwargs: None
    fake = SyntheticNative('bt_api_ctp.ctp._ctp')
    fake.__file__ = '<synthetic module; no binary loaded>'
    sys.modules[fake.__name__] = fake
elif mode != 'fallback':
    raise ValueError(mode)

import pytest
rc = pytest.main(['-p', 'no:cacheprovider', '-o', 'addopts=', '--import-mode=prepend', '--basetemp', basetemp, '-q', os.path.join(root, 'tests', 'unit', 'test_ctp_admission_authority.py')])
base = sys.modules.get('bt_api_ctp.ctp._ctp_base')
sdk = sys.modules.get('bt_api_py')
actual_native = sys.modules.get('bt_api_ctp.ctp._ctp')
print('HARNESS mode=', mode, 'sdk=', getattr(sdk, '__file__', None), 'provider=', getattr(base, '__file__', None), 'native_loaded_flag=', base.is_ctp_native_loaded() if base else None, 'finder_blocks=', len(blocker.hits), 'actual_native_is_synthetic=', actual_native is fake if fake is not None else actual_native is None, flush=True)
if fake is None:
    assert actual_native is None
    assert base is not None and not base.is_ctp_native_loaded()
else:
    assert actual_native is fake
    assert base is not None and base.is_ctp_native_loaded()
raise SystemExit(rc)
