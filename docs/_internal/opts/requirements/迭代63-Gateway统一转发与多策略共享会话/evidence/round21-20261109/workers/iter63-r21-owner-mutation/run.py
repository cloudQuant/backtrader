"""Offline behavior mutations, not execution of a historical revision."""
import importlib.util
from pathlib import Path
import sys
import pytest
import bt_api_py  # Resolve the real package and all unrelated modules normally.

source = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api_py/gateway_direct_owner.py').read_text()
kind = sys.argv[1]
if kind == 'expired_pop':
    old = '''                    elif type(task) is _ServiceTask:\n                        self._finish_service_locked(task, error="SERVICE_CALL_EXPIRED")\n'''
    assert source.count(old) == 1
    source = source.replace(old, '')
    old = '''            if type(task) is _ServiceTask:\n                if expired:\n                    continue\n'''
    new = '''            if type(task) is _ServiceTask:\n                if expired:\n                    with self._condition:\n                        self._finish_service_locked(task, error="SERVICE_CALL_EXPIRED")\n                    continue\n'''
    assert source.count(old) == 1
    source = source.replace(old, new)
    test = 'test_expired_pop_and_cancel_are_atomic_under_controlled_interleaving'
elif kind == 'close_reentry':
    old = '''    def close(self, timeout_seconds: float) -> bool:\n        self._check_service_caller()\n'''
    new = '''    def close(self, timeout_seconds: float) -> bool:\n        self._check_pid()\n'''
    assert source.count(old) == 1
    source = source.replace(old, new)
    old = '        return self._done.wait(timeout)\n'
    new = '        return self._done.wait(min(timeout, 0.01))  # mutation harness safety cap\n'
    assert source.count(old) == 1
    source = source.replace(old, new)
    test = 'test_callback_cannot_start_or_close_owner_and_owner_continues'
else:
    raise SystemExit('unknown mutation')
path = Path('/tmp/iter63-r21-owner-mutation') / (kind + '.py')
path.write_text(source)
spec = importlib.util.spec_from_file_location('bt_api_py.gateway_direct_owner', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print('MUTATION',kind,'MODULE',path,flush=True)
raise SystemExit(pytest.main(['-q', 'tests/unit/test_iter63_gateway_owner_service_calls.py::' + test]))
