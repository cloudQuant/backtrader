import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
QA = Path('D:/opq' + uuid4().hex[:8])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
INDEX = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r33-root-preparation-source-fake-r2-r1-2026-10-09/source-index.json'
INDEX_SHA = 'a76dca4d4e86340e8234d2c26c3e03b2d91ea726339e7833b8d08f4e37b0d044'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


index_raw = INDEX.read_bytes()
assert sha(index_raw) == INDEX_SHA
index = json.loads(index_raw)
rows = index['candidate_sources'] + index['fixed_dependencies']
assert len(rows) == 15
pins = {row['path']: {'sha256': row['sha256'], 'bytes': row['bytes']} for row in rows}
pins[INDEX.relative_to(ROOT).as_posix()] = {'sha256': INDEX_SHA, 'bytes': len(index_raw)}
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode()
for relative, record in pins.items():
    raw = (ROOT / relative).read_bytes()
    assert len(raw) == record['bytes'] and sha(raw) == record['sha256'], relative
QA.mkdir(exist_ok=False)
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
arguments = [str(ROOT / row['path']) for row in index['candidate_sources'] if row['path'].startswith('tests/')]
arguments += ['-q', '--tb=short', '-c', str(QA / 'pytest.ini'),
              '--confcutdir=' + str(ROOT / 'tests/unit/scripts'),
              '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + str(QA / 'bt')]
runner = '''import ctypes, sys, pathlib, socket, ssl, http.client, multiprocessing, multiprocessing.process, _winapi
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest, colorama
def deny(*args, **kwargs):
    raise AssertionError('actual_private_opaque_native_sdk_network_process_pipe_operation_forbidden')
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
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value or value.endswith(('.dll', '.exe')):
            deny()
sys.addaudithook(audit)
class Origins:
    def pytest_sessionfinish(self, session, exitstatus):
        matching = [m for name, m in tuple(sys.modules.items()) if name.endswith('test_iteration41_optional16_r33_root_preparation_driver_r2_source_fake')]
        assert len(matching) == 1
        module = matching[0].DRIVER
        assert pathlib.Path(module.__file__).resolve() == pathlib.Path(SOURCE_ROOT, 'scripts/iteration41_optional16_r33_root_preparation_driver_r2.py').resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[Origins()]))
'''
env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=QA, env=env, capture_output=True, timeout=60)
output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
print(json.dumps({'root_source_qa': output.strip(), 'exit_code': completed.returncode}))
assert completed.returncode == 0 and '13 passed' in output and 'warning' not in output
for relative, record in pins.items():
    raw = (ROOT / relative).read_bytes()
    assert len(raw) == record['bytes'] and sha(raw) == record['sha256'], relative
assert git('rev-parse', 'HEAD').strip().decode() == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {'schema': 'iteration41.optional16.preparation-r2.root-source-qa.v1', 'parent': parent,
          'branch': 'dev', 'passed': 13, 'exit_code': 0, 'warning_count': 0,
          'exact_pre_post_pins': pins, 'driver_module_origin_verified': True,
          'nested_v4_v3_production_loader_binding_asserted_by_selected_tests': True,
          'private_opaque_native_sdk_network_real_process_pipe_denial_before_candidate_imports': True,
          'production_root_scope_full_map_profiler_installer_activation_verified': False,
          'actual_account_provider': False, 'formal_case_pass': False,
          'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)}
with (ROOT / '.codex-tmp/optional16_preparation_r2_root_source_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({k: v for k, v in result.items() if k != 'exact_pre_post_pins'}))
