import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
REVIEW = E + 'iteration41-tradelogger-config-snapshot-seam-independent-review-r1-2026-10-09/review.json'
EXPECTED = {
    'backtrader/observers/trade_logger.py': (134254, '9700bf8ab0de0a1b36786cd2ba5c085b387378f597fe64b085d022ee33187a3c'),
    'backtrader/strategy.py': (151163, '1b4f02a5e59774d057545fbc73b17e40c84add6c557c59c4a320d0b3223f043c'),
    'tests/unit/observers/test_trade_logger_config_snapshot.py': (7956, '3e9baf54b825ea07adcd1066f6b3434d1346baf26a0d13237a5aad311e22553c'),
    REVIEW: (7689, 'f75112b302cfb8fa7a6cdf86439058436708a32d886935e636095cb084313543'),
}
TESTS = [
    'tests/unit/observers/test_trade_logger_config_snapshot.py',
    'tests/unit/observers/test_trade_logger_monitoring.py',
    'tests/unit/observers/test_trade_logger_internal_errors.py',
    'tests/unit/observers/test_trade_logger_edge_cases.py',
    'tests/integration/test_trade_logger.py',
    'tests/integration/test_trade_logger_report.py',
    'tests/integration/test_trade_logger_runtime.py',
]
DEPENDENCIES = [
    'backtrader/cerebro.py', 'backtrader/_cerebro/execution.py',
    'backtrader/observer.py', 'backtrader/lineiterator.py',
    'backtrader/__init__.py', 'backtrader/stores/btapistore.py',
    'backtrader/events.py', 'backtrader/channel.py',
    'backtrader/brokers/tickbroker.py', 'tests/fixtures/fake_btapi.py',
]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout

pins = {}
for path in dict.fromkeys([*EXPECTED, *TESTS, *DEPENDENCIES]):
    raw = (ROOT / path).read_bytes()
    record = (len(raw), sha(raw))
    if path in EXPECTED:
        assert record == EXPECTED[path], path
    pins[path] = {'bytes': record[0], 'sha256': record[1]}
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode()
qa = Path('D:/tlq' + uuid4().hex[:8])
qa.mkdir(exist_ok=False)
(qa / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
args = [str(ROOT / path) for path in TESTS] + [
    '-q', '--tb=short', '-c', str(qa / 'pytest.ini'),
    '--confcutdir=' + str(ROOT / 'tests'), '-p', 'no:asyncio',
    '-p', 'no:cacheprovider', '--basetemp=' + str(qa / 'bt'),
]
runner = r'''
import sys, ctypes, pathlib, socket, ssl, http.client, multiprocessing.process, _winapi
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import numpy, pandas, pytz, pytest, colorama, platform, statsmodels.api
platform.uname()
assert not any(name == 'backtrader' or name.startswith(('backtrader.', 'bt_api')) for name in sys.modules)
def deny(*args, **kwargs):
    raise AssertionError('private_native_sdk_network_real_process_pipe_operation_forbidden')
ctypes.WinDLL = deny
multiprocessing.process.BaseProcess.start = deny
for member in ['CreateProcess', 'CreatePipe', 'CreateNamedPipe', 'ConnectNamedPipe']:
    if hasattr(_winapi, member):
        setattr(_winapi, member, deny)
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect', 'socket.getaddrinfo', 'ctypes.dlopen', '_winapi.CreateProcess'}:
        deny()
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        deny()
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace(chr(92), '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value or value.endswith(('.dll', '.exe')):
            deny()
sys.addaudithook(audit)
for probe in ['D:' + chr(92) + 'private' + chr(92) + '.env', 'D:/private/config.yaml', 'D:' + chr(92) + 'private-capture.json', 'C:' + chr(92) + 'fake.dll']:
    try:
        sys.audit('open', probe, 'r', 0)
    except AssertionError:
        pass
    else:
        raise AssertionError('private_path_audit_guard_selfcheck_failed')
class Origins:
    def pytest_sessionfinish(self, session, exitstatus):
        if exitstatus != 0:
            return
        for name, relative in {'backtrader': 'backtrader/__init__.py', 'backtrader.strategy': 'backtrader/strategy.py', 'backtrader.observers.trade_logger': 'backtrader/observers/trade_logger.py', 'backtrader.cerebro': 'backtrader/cerebro.py'}.items():
            assert pathlib.Path(sys.modules[name].__file__).resolve() == pathlib.Path(SOURCE_ROOT, relative).resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[Origins()]))
'''
env = {key: value for key, value in os.environ.items() if key.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(args) + '\n' + runner
completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=qa, env=env, capture_output=True, timeout=60)
output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
print(json.dumps({'qa': output.strip(), 'exit_code': completed.returncode}))
assert completed.returncode == 0 and '76 passed, 15 warnings' in output
assert output.count('PytestUnknownMarkWarning: Unknown pytest.mark.integration') == 14
assert output.count('DeprecationWarning: backtrader.feeds.quandl is deprecated') == 1
for path, record in pins.items():
    raw = (ROOT / path).read_bytes()
    assert len(raw) == record['bytes'] and sha(raw) == record['sha256'], path
assert git('rev-parse', 'HEAD').strip().decode() == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {
    'schema': 'iteration41.tradelogger.config_snapshot.root-source-qa.r2.v1',
    'branch': 'dev', 'parent': parent, 'passed': 76, 'exit_code': 0, 'warning_count': 15,
    'warnings': {'existing_quandl_deprecation': 1, 'isolated_config_unregistered_integration_mark': 14},
    'exact_pre_post_pins': pins, 'four_core_module_origins_verified': True, 'private_path_audit_guard_selfchecks': 4,
    'dependencies_preloaded_before_guard': ['numpy', 'pandas', 'pytz', 'pytest', 'colorama', 'statsmodels.api', 'platform.uname'],
    'candidate_import_after_private_native_sdk_network_real_process_pipe_denial': True,
    'evidence_level': 'SOURCE_FAKE_COMPONENT_ONLY', 'actual_account_provider': False,
    'formal_case_pass': False, 'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr),
}
with (ROOT / '.codex-tmp/tradelogger_snapshot_root_source_qa_r2_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({key: value for key, value in result.items() if key != 'exact_pre_post_pins'}))
