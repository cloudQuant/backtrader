import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
QA = Path('D:/bwq' + uuid4().hex[:8])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
PINS = {
    'examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py': '4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63',
    'scripts/iteration41_binance_th01_account_window_candidate_r2.py': '698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6',
    'tests/unit/live_certification/test_binance_th01_account_window_candidate_r2.py': 'd7fad941b1326bd21e37fb5340002c675656e3eb5664ce7b3a93ff43f7751deb',
    'scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py': '1186154869ed2c9ec8389d867e8caaeb492b3d2ad45cfda407950cb47bd848de',
    'tests/unit/live_certification/test_binance_th01_spawn_pipe_gate_r1.py': 'a0b65255415056b64b883c35789271b3c07c138e45c220be56c367f692e0d562',
    'examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py': '290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f',
    'backtrader_runtime/certification_roundtrip_private.py': 'b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd',
    'backtrader_runtime/certification_binance_roundtrip_r3_cli.py': '62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76',
}
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode()
for relative, pin in PINS.items():
    assert sha((ROOT / relative).read_bytes()) == pin, relative
QA.mkdir(exist_ok=False)
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
test_paths = [str(ROOT / p) for p in PINS if p.startswith('tests/')]
runner = '''import ctypes, sys, pathlib, socket, ssl, http.client, multiprocessing, multiprocessing.process, _winapi
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest, colorama
def deny(*args, **kwargs):
    raise AssertionError('actual_private_native_sdk_network_process_pipe_operation_forbidden')
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
        value = str(args[0]).replace('\\\\', '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value:
            deny()
sys.addaudithook(audit)
class Origins:
    def pytest_sessionfinish(self, session, exitstatus):
        expected = {
            '_test_iteration41_th01_account_window_candidate_r2': 'examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py',
            '_iteration41_binance_th01_spawn_pipe_gate_r1_sourcefake': 'scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py',
        }
        for name, relative in expected.items():
            if name in sys.modules:
                assert pathlib.Path(sys.modules[name].__file__).resolve() == (pathlib.Path(SOURCE_ROOT) / relative).resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[Origins()]))
'''
env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
checks = []
for index, (test_path, expected_count) in enumerate(zip(test_paths, [19, 15])):
    arguments = [test_path, '-q', '--tb=short', '-c', str(QA / 'pytest.ini'),
                 '--confcutdir=' + str(ROOT / 'tests/unit/live_certification'),
                 '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + str(QA / ('bt' + str(index)))]
    code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
    completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=QA,
                               env=env, capture_output=True, timeout=60)
    output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
    print(json.dumps({'source_qa': output.strip(), 'exit_code': completed.returncode}))
    assert completed.returncode == 0 and str(expected_count) + ' passed' in output and 'warning' not in output
    checks.append({'test_path': test_path, 'passed': expected_count, 'exit_code': 0, 'warning_count': 0,
                   'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)})
for relative, pin in PINS.items():
    assert sha((ROOT / relative).read_bytes()) == pin, relative
assert git('rev-parse', 'HEAD').strip().decode() == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {'schema': 'iteration41.binance.th01.window-gate.root-source-qa.v1', 'parent': parent,
          'branch': 'dev', 'passed': 34, 'exit_code': 0, 'warning_count': 0,
          'exact_pre_post_pins': PINS, 'module_origins_verified': True,
          'private_native_sdk_network_real_process_pipe_denial_before_candidate_imports': True,
          'actual_account_provider': False, 'formal_case_pass': False, 'fresh_process_checks': checks,
          'prior_combined_harness': {'passed': 29, 'failed': 5, 'exit_code': 1,
                                    'repository_basetemp_rejected': True,
                                    'function_valued_socket_class_observed': True,
                                    'shared_state_root_cause_established': False,
                                    'combined_process_acceptance': False},
          'prior_isolated_harness_without_ssl_bootstrap': {
              'passed': 15, 'failed': 4, 'exit_code': 1,
              'cold_ssl_subclass_of_fake_socket_failed': True,
              'production_source_unchanged': True,
              'acceptance': False}}
with (ROOT / '.codex-tmp/binance_th01_window_gate_root_source_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({k: v for k, v in result.items() if k != 'exact_pre_post_pins'}))
