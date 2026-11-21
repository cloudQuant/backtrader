"""Run exactly one public R71-148 test against a single in-memory mutation."""
import hashlib
import os
import sys
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'backtrader/service/service_recovery_attestation.py'
TEST = ROOT / 'tests/unit/test_iter71_service_recovery_attestor_fill_validation.py'
ALLOWED = (os.path.normcase(os.path.realpath(str(ROOT))),
           os.path.normcase(os.path.realpath(sys.base_prefix)))

def guard(event, args):
    if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system', 'os.spawn', 'ctypes.dlopen'}:
        raise PermissionError('blocked-operation:' + event)
    if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.path.normcase(os.path.realpath(os.fsdecode(args[0])))
        permitted = False
        for prefix in ALLOWED:
            try:
                permitted = permitted or os.path.commonpath((path, prefix)) == prefix
            except ValueError:
                continue
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else ''
        writing = any(c in mode for c in 'wax+') or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if not permitted or writing:
            print('BLOCKED_FILE', 'permitted=', permitted, 'writing=', writing, 'mode=', mode,
                  'flags=', flags, flush=True)
            raise PermissionError('blocked-file-access')

sys.addaudithook(guard)
for event, args in [('socket.connect', ()), ('subprocess.Popen', ()), ('ctypes.dlopen', ())]:
    try:
        sys.audit(event, *args)
    except PermissionError:
        pass
    else:
        raise AssertionError('guard selfcheck failed: ' + event)

sys.path.insert(0, str(Path(sys.base_prefix) / 'Lib' / 'site-packages'))
import pytest  # exact real pytest.raises; no plugin discovery or conftest

case, kind = sys.argv[1:]
source_bytes = SOURCE.read_bytes()
test_bytes = TEST.read_bytes()
source = source_bytes.decode('utf-8')
mutations = {
    'currency': ('            or context["commission_currency"] != fill_currency',
                 'test_distinct_valid_commission_currencies_are_a_mismatch'),
    'time': ('            or context["quote_as_of_ns"] > match_time_ns',
             'test_quote_must_not_be_newer_than_the_exact_match_time'),
}
needle, test_name = mutations[case]
needle += '\r\n' if '\r\n' in source else '\n'
if source.count(needle) != 1:
    raise AssertionError('mutation site not unique')
if kind == 'mutant':
    source = source.replace(needle, '', 1)
elif kind != 'clean':
    raise AssertionError('unknown mode')

print('case=', case, 'mode=', kind, 'source_sha256=', hashlib.sha256(source_bytes).hexdigest(),
      'test_sha256=', hashlib.sha256(test_bytes).hexdigest(),
      'executed_source_sha256=', hashlib.sha256(source.encode('utf-8')).hexdigest(),
      'target=', test_name, 'synthetic_guard_selfchecks=3', flush=True)

package = types.ModuleType('backtrader'); package.__path__ = []
service = types.ModuleType('backtrader.service'); service.__path__ = []
name = 'backtrader.service.service_recovery_attestation'
module = types.ModuleType(name); module.__file__ = str(SOURCE)
sys.modules['backtrader'] = package
sys.modules['backtrader.service'] = service
sys.modules[name] = module
exec(compile(source, str(SOURCE), 'exec'), module.__dict__)
test_module = types.ModuleType('target_test'); test_module.__file__ = str(TEST)
exec(compile(test_bytes, str(TEST), 'exec'), test_module.__dict__)
getattr(test_module, test_name)()
print('TARGET_PASS', flush=True)
