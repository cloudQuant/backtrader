import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
QA = Path('D:/mlq' + uuid4().hex[:8])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
INDEX = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/source-index.json'
INDEX_SHA = 'abc6e49afab4fad7d44dc70474cfc993e212e71c56270b7d065374da63da9bc8'
PINS = {
    'scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r2.py': '0c9067ba1a759a6843bc7249ffbe38a09f30c6d5f7e5ab1612cd60846d83e976',
    'tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py': 'd6df3de0af5695d6842c711597dddd998dc3f394144be89d720c851e1c600848',
    'scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py': 'c53833b20238cb82d491bf7972508a604e56c8ad3158cada7060f9910629a78e',
    'tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_patch_r2_source_fake.py': 'c413205ebd5053d13396368dd23c88b9e7ac431881802f9319c2425eb559bfc5',
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout

index_raw = INDEX.read_bytes()
assert sha(index_raw) == INDEX_SHA
rows = json.loads(index_raw)['rows']
assert len(rows) == 20
PINS.update({row['path']: row['sha256'] for row in rows})
PINS[INDEX.relative_to(ROOT).as_posix()] = INDEX_SHA
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode()
for relative, pin in PINS.items():
    assert sha((ROOT / relative).read_bytes()) == pin, relative
QA.mkdir(exist_ok=False)
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
arguments = [str(ROOT / relative) for relative in PINS if relative.startswith('tests/unit/scripts/')]
arguments += ['-q', '--tb=short', '-c', str(QA / 'pytest.ini'),
              '--confcutdir=' + str(ROOT / 'tests/unit/scripts'),
              '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + str(QA / 'bt')]
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
            '_m01_readonly_monitor_v3.current_reader': 'examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py',
            '_m01_readonly_monitor_v2.job_supervisor': 'examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py',
            '_m01_readonly_monitor_v2.worker': 'examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py',
        }
        for name, relative in expected.items():
            assert name in sys.modules
            assert pathlib.Path(sys.modules[name].__file__).resolve() == (pathlib.Path(SOURCE_ROOT) / relative).resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[Origins()]))
'''
env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=QA,
                           env=env, capture_output=True, timeout=60)
output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
print(json.dumps({'root_source_qa': output.strip(), 'exit_code': completed.returncode}))
assert completed.returncode == 0 and '14 passed' in output and 'warning' not in output
for relative, pin in PINS.items():
    assert sha((ROOT / relative).read_bytes()) == pin, relative
assert git('rev-parse', 'HEAD').strip().decode() == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {'schema': 'iteration41.okx.m01.lifecycle-r2.root-source-qa.v1', 'parent': parent,
          'branch': 'dev', 'passed': 14, 'exit_code': 0, 'warning_count': 0,
          'exact_pre_post_pins': PINS, 'module_origins_verified': True,
          'private_native_sdk_network_real_process_pipe_denial_before_candidate_imports': True,
          'actual_account_provider': False, 'formal_case_pass': False,
          'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)}
with (ROOT / '.codex-tmp/okx_m01_lifecycle_r2_root_source_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({k: v for k, v in result.items() if k != 'exact_pre_post_pins'}))
