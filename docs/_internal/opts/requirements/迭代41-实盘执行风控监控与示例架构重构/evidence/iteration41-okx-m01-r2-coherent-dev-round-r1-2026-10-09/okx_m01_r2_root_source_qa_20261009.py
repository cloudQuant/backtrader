import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
E = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence'
PACKET = E / 'iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09'
QA = Path('D:/mq' + uuid4().hex[:4])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
TEST = 'tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.run(['git', '-c', 'core.longpaths=true', *args], cwd=ROOT, capture_output=True, check=True).stdout

assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode('ascii')
index = json.loads((PACKET / 'source-index.json').read_bytes())
assert index['source_map_file_sha256'] == 'db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3'
assert len(index['rows']) == 20 and index['runtime_source_count'] == 19
QA.mkdir(exist_ok=False)
rows = []
for row in index['rows']:
    relative = row['path']
    raw = (ROOT / relative).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], relative
    target = QA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    rows.append({'path': relative, 'sha256': row['sha256'], 'size': row['bytes']})
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
runner = '''import ctypes, pathlib, socket, ssl, sys
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest, colorama
def deny(*args, **kwargs):
    raise AssertionError('actual_private_native_sdk_network_process_operation_forbidden')
ctypes.WinDLL = deny
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect', 'socket.getaddrinfo', 'ctypes.dlopen'}:
        deny()
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        deny()
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace('\\\\', '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'iteration41-okx-m01-v3-deployment' in value or 'iteration41-okx-c01-root' in value:
            deny()
sys.addaudithook(audit)
class OriginGuard:
    def pytest_sessionfinish(self, session, exitstatus):
        names = ['_certification.m01_private_monitor_v2', '_m01_readonly_monitor_v2.current_types', '_m01_readonly_monitor_v2.job_supervisor', '_m01_readonly_monitor_v2.worker', '_m01_readonly_monitor_v3.current_reader', '_m01_readonly_monitor_v3.entry', '_m01_readonly_monitor_v3.issuer']
        venue = pathlib.Path(SOURCE_ROOT) / 'examples/000_live_certification/okx_penetration'
        for name in names:
            actual = pathlib.Path(sys.modules[name].__file__).resolve()
            expected = venue / (name.replace('.', '/') + '.py')
            assert actual == expected.resolve(), name
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[OriginGuard()]))
'''
arguments = [str(ROOT / TEST), '-q', '--tb=short', '-c', str(QA / 'pytest.ini'), '--confcutdir=' + str((ROOT / TEST).parent), '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + str(QA / 'bt')]
code = 'SOURCE_ROOT=' + repr(str(ROOT)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH','PYTHONHOME','PYTEST_ADDOPTS','PYTEST_PLUGINS'}}
env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
completed = subprocess.run([PY, '-I', '-S', '-B', '-X', 'utf8', '-c', code], cwd=QA, env=env, capture_output=True, timeout=60)
output = completed.stdout.decode('utf-8', errors='replace') + completed.stderr.decode('utf-8', errors='replace')
print(json.dumps({'source_qa': output.strip(), 'exit_code': completed.returncode}), flush=True)
assert completed.returncode == 0 and '13 passed' in output and 'warning' not in output
for row in rows:
    assert sha((QA / row['path']).read_bytes()) == row['sha256']
    assert sha((ROOT / row['path']).read_bytes()) == row['sha256']
assert git('rev-parse', 'HEAD').strip().decode('ascii') == parent
assert not git('diff', '--cached', '--name-only', '-z')
result = {'schema': 'iteration41.okx.m01.r2.root_source_qa.v1', 'scope': 'SOURCE_FAKE_COMPONENT_ONLY', 'branch': 'dev', 'parent': parent, 'canonical_fixed_path_source_qa': {'passed': 13, 'exit_code': 0, 'warning_count': 0, 'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)}, 'prior_relocated_full_file_qa': {'passed': 10, 'failed': 3, 'exit_code': 1, 'reason': 'fixed_canonical_source_origins_not_relocatable'}, 'relocated_full_file_acceptance': False, 'source_pre_post_pins_match': True, 'module_origins_verified': True, 'hard_deny_private_native_sdk_network_process_leaves': True, 'actual_account_provider': False, 'formal_m01_pass_count': 0, 'index_empty': True, 'rows': rows}
with (ROOT / '.codex-tmp/okx_m01_r2_root_source_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, sort_keys=True), flush=True)
