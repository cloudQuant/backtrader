import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
HELPER = 'scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py'
TEST = 'tests/unit/scripts/test_iteration41_okx_m01_local_source_lease_reconciliation_r7.py'
REVIEW = E + 'iteration41-okx-m01-local-source-lease-reconciliation-independent-review-r7-2026-10-09/README.md'
QA = Path('D:/mrq' + uuid4().hex[:8])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def literal(node, known):
    if isinstance(node, ast.Name):
        return known[node.id]
    if isinstance(node, ast.Dict):
        return {literal(key, known): literal(value, known) for key, value in zip(node.keys, node.values)}
    return ast.literal_eval(node)


helper_raw = (ROOT / HELPER).read_bytes()
assert len(helper_raw) == 67503 and sha(helper_raw) == '8e7e3fb7e9b0e51968e6d8a3bdc47793c7ca276e55eb9cfd60367270aa8ebef5'
known = {}
for node in ast.parse(helper_raw).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            known[node.targets[0].id] = literal(node.value, known)
        except (ValueError, KeyError, TypeError):
            pass
fixed = dict(known['_PUBLIC_SOURCE_PINS'])
assert len(fixed) == 27
fixed.update({HELPER: '8e7e3fb7e9b0e51968e6d8a3bdc47793c7ca276e55eb9cfd60367270aa8ebef5',
              TEST: '25ae3dd5bc34b0180e270ab6dc9985bbbaa008617cadc16ebd881c18aade4a88',
              REVIEW: '6428d48a75d7d8620f0c82ef682cabeda87e53b07ecc504bc814cec7aec2b9ee',
              known['CUV2_RELATIVE']: known['CUV2_SOURCE_SHA256'],
              known['OBSERVATION_RELATIVE']: known['OBSERVATION_SHA256'],
              known['RETAINED_FACTS_RELATIVE']: known['RETAINED_FACTS_SHA256']})
pins = {}
for relative, digest in fixed.items():
    raw = (ROOT / relative).read_bytes()
    assert sha(raw) == digest, relative
    pins[relative] = {'sha256': digest, 'bytes': len(raw)}
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode()
QA.mkdir(exist_ok=False)
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
arguments = [str(ROOT / TEST), '-q', '--tb=short', '-c', str(QA / 'pytest.ini'),
             '--confcutdir=' + str(ROOT / 'tests/unit/scripts'), '-p', 'no:asyncio',
             '-p', 'no:cacheprovider', '--basetemp=' + str(QA / 'bt')]
runner = '''import ctypes, sys, pathlib, socket, ssl, http.client, multiprocessing, multiprocessing.process, _winapi
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest, colorama
def deny(*args, **kwargs):
    raise AssertionError('actual_private_opaque_external_software_native_sdk_network_process_pipe_operation_forbidden')
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
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value or value.endswith(('.dll', '.exe')) or value == 'd:/temp/iteration41-root-public-custody-v2.py':
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
        module = sys.modules['_m01_source_lease_reconciliation_r7_test']
        assert pathlib.Path(module.__file__).resolve() == pathlib.Path(SOURCE_ROOT, HELPER_PATH).resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[Origins()]))
'''
env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nHELPER_PATH=' + repr(HELPER) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=QA, env=env, capture_output=True, timeout=60)
output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
print(json.dumps({'root_source_qa': output.strip(), 'exit_code': completed.returncode}))
assert completed.returncode == 0 and '17 passed' in output and 'warning' not in output
for path, record in pins.items():
    raw = (ROOT / path).read_bytes()
    assert len(raw) == record['bytes'] and sha(raw) == record['sha256'], path
assert git('rev-parse', 'HEAD').strip().decode() == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {'schema': 'iteration41.okx.m01.reconciliation-r7.root-source-qa.v1', 'parent': parent,
          'branch': 'dev', 'passed': 17, 'exit_code': 0, 'warning_count': 0,
          'exact_pre_post_pins': pins, 'helper_module_origin_verified': True,
          'private_opaque_external_software_native_sdk_network_real_process_pipe_denial_before_candidate_imports': True,
          'actual_original_lease_close_verified': False, 'actual_account_provider': False,
          'formal_case_pass': False, 'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)}
with (ROOT / '.codex-tmp/okx_m01_reconciliation_r7_root_source_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({k: v for k, v in result.items() if k != 'exact_pre_post_pins'}))
