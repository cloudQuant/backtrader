"""Root's one preparation-only launch. Use -i and preserve its live namespace."""
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import stat
import sys
from types import FunctionType, ModuleType

ROOT_CALLER_PATH = Path('D:/source_code/backtrader/.codex-tmp/simnow_v20_root_preparation_actual_caller_r2_20261009.py')
ROOT_CALLER_MODULE_NAME = '_c01_simnow_v20_root_preparation_actual_caller_r2'
ROOT_CALLER_PIN = (24722, '359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0')
ROOT_CUV2_PATH = Path('D:/temp/iteration41-root-public-custody-v2.py')
ROOT_CUV2_PIN = (2344, 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246')
ROOT_PREPARATION_LAUNCH_STATE = {
    'phase': 'bounded_reads',
    'invocation_count': 0,
    'held': (),
    'summary': None,
    'source_phase': None,
    'exception_category': None,
    '_exception': None,
}


def _root_stat_token(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_mode, getattr(value, 'st_file_attributes', 0))


def _root_read_fixed(path, expected, cap):
    assert path in (ROOT_CALLER_PATH, ROOT_CUV2_PATH)
    assert type(expected[0]) is int and 0 < expected[0] <= cap
    before = path.stat(follow_symlinks=False)
    assert stat.S_ISREG(before.st_mode) and not getattr(before, 'st_file_attributes', 0) & 0x400
    assert before.st_size == expected[0]
    resolved = path.resolve(strict=True)
    assert resolved == path
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        assert _root_stat_token(opened) == _root_stat_token(before)
        raw = stream.read(expected[0] + 1)
        assert _root_stat_token(os.fstat(stream.fileno())) == _root_stat_token(opened)
    assert _root_stat_token(path.stat(follow_symlinks=False)) == _root_stat_token(before)
    assert path.resolve(strict=True) == resolved
    assert len(raw) == expected[0] and hashlib.sha256(raw).hexdigest() == expected[1]
    return raw


def _root_safe_exception_category(exc, caller_module):
    if type(exc) is caller_module.__dict__.get('RootPreparationCallerError'):
        return 'root_caller_contract_error'
    attempts = caller_module.__dict__.get('_ATTEMPTS')
    if type(attempts) is list and attempts:
        prep = getattr(attempts[-1], 'preparation_module', None)
        preparation_error = prep.__dict__.get('RootPreparationError') if type(prep) is ModuleType else None
        if type(exc) is preparation_error:
            return 'root_preparation_source_error'
    return 'other_preparation_exception'


root_caller_source_bytes = _root_read_fixed(ROOT_CALLER_PATH, ROOT_CALLER_PIN, 2 * 1024 * 1024)
root_cuv2_source_bytes = _root_read_fixed(ROOT_CUV2_PATH, ROOT_CUV2_PIN, 8 * 1024 * 1024)
assert ROOT_CALLER_MODULE_NAME not in sys.modules
root_simnow_v20_caller_module_r2 = ModuleType(ROOT_CALLER_MODULE_NAME)
root_simnow_v20_caller_module_r2.__file__ = str(ROOT_CALLER_PATH)
root_simnow_v20_caller_module_r2.__package__ = ''
root_simnow_v20_caller_module_r2.__loader__ = None
root_simnow_v20_caller_module_r2.__cached__ = None
root_simnow_v20_caller_module_r2.__spec__ = importlib.machinery.ModuleSpec(
    ROOT_CALLER_MODULE_NAME, loader=None, origin=str(ROOT_CALLER_PATH))
sys.modules[ROOT_CALLER_MODULE_NAME] = root_simnow_v20_caller_module_r2
ROOT_PREPARATION_LAUNCH_STATE['held'] = (root_simnow_v20_caller_module_r2,
    root_caller_source_bytes, root_cuv2_source_bytes)
exec(compile(root_caller_source_bytes, str(ROOT_CALLER_PATH), 'exec', dont_inherit=True),
     root_simnow_v20_caller_module_r2.__dict__)
root_simnow_v20_entry_r2 = root_simnow_v20_caller_module_r2.prepare_once
assert type(root_simnow_v20_entry_r2) is FunctionType
assert root_simnow_v20_entry_r2.__globals__ is root_simnow_v20_caller_module_r2.__dict__
root_simnow_v20_entry_code_r2 = root_simnow_v20_entry_r2.__code__
ROOT_PREPARATION_LAUNCH_STATE['phase'] = 'preparation_entry'
ROOT_PREPARATION_LAUNCH_STATE['invocation_count'] = 1
try:
    root_simnow_v20_preparation_attempt_r2 = root_simnow_v20_entry_r2(root_cuv2_source_bytes)
except BaseException as root_simnow_v20_preparation_exception_r2:
    ROOT_PREPARATION_LAUNCH_STATE['_exception'] = root_simnow_v20_preparation_exception_r2
    ROOT_PREPARATION_LAUNCH_STATE['phase'] = 'preparation_exception_retained'
    ROOT_PREPARATION_LAUNCH_STATE['source_phase'] = 'prepare_once_entry'
    ROOT_PREPARATION_LAUNCH_STATE['exception_category'] = _root_safe_exception_category(
        root_simnow_v20_preparation_exception_r2, root_simnow_v20_caller_module_r2)
    ROOT_PREPARATION_LAUNCH_STATE['summary'] = root_simnow_v20_caller_module_r2.last_attempt_summary()
else:
    ROOT_PREPARATION_LAUNCH_STATE['phase'] = 'prepared_host_retained'
    ROOT_PREPARATION_LAUNCH_STATE['source_phase'] = 'prepare_once_returned'
    ROOT_PREPARATION_LAUNCH_STATE['held'] += (root_simnow_v20_preparation_attempt_r2,)
    ROOT_PREPARATION_LAUNCH_STATE['summary'] = root_simnow_v20_preparation_attempt_r2.public_summary()
assert sys.modules[ROOT_CALLER_MODULE_NAME] is root_simnow_v20_caller_module_r2
assert root_simnow_v20_caller_module_r2.prepare_once is root_simnow_v20_entry_r2
assert root_simnow_v20_entry_r2.__code__ is root_simnow_v20_entry_code_r2
assert root_simnow_v20_entry_r2.__globals__ is root_simnow_v20_caller_module_r2.__dict__
print(json.dumps({'launch_phase': ROOT_PREPARATION_LAUNCH_STATE['phase'],
    'invocation_count': ROOT_PREPARATION_LAUNCH_STATE['invocation_count'],
    'source_phase': ROOT_PREPARATION_LAUNCH_STATE['source_phase'],
    'exception_category': ROOT_PREPARATION_LAUNCH_STATE['exception_category'],
    'caller_entry_binding_preserved': True,
    'summary': ROOT_PREPARATION_LAUNCH_STATE['summary']}, sort_keys=True), flush=True)
