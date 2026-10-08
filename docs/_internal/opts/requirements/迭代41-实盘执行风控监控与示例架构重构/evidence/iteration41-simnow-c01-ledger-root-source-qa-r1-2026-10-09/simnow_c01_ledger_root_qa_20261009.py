import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
QA = Path('D:/sq' + uuid4().hex[:4])
PY = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
SITE = 'D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages'
TEST = 'tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py'
CANDIDATE = {
    'examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py': '4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a',
    TEST: 'a4f4d643fc3ca12c6e162e418312ec5b97291effaebefbf6f55573ef593fc88d',
    'examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1_field_map.md': 'c9912ba8793384d2057619a027db5aa0119ff1b81516021eb9c1dd06a45a7ec6',
}
BASELINE = {
    'backtrader_runtime/certification_simnow_c01_native_v4.py': '66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66',
    'backtrader_runtime/certification_simnow_c01_v3_protocol.py': 'c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160',
}
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def git(*args):
    return subprocess.run(['git', '-c', 'core.longpaths=true', *args], cwd=ROOT, capture_output=True, check=True).stdout
assert git('branch', '--show-current').strip() == b'dev'
assert not git('diff', '--cached', '--name-only', '-z')
parent = git('rev-parse', 'HEAD').strip().decode('ascii')
QA.mkdir(exist_ok=False)
rows = []
for source, mapping in [('candidate', CANDIDATE), ('tracked_baseline', BASELINE)]:
    for relative, pin in mapping.items():
        raw = (ROOT / relative).read_bytes()
        assert sha(raw) == pin, relative
        if source == 'tracked_baseline':
            assert not git('diff', '--', relative)
            committed = git('cat-file', '--filters', 'HEAD:' + relative)
            assert committed == raw
        target = QA / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        rows.append({'path': relative, 'sha256': pin, 'size': len(raw), 'source': source})
(QA / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
runner = '''import ctypes, hashlib, pathlib, sys, types
sys.path[:0] = [SOURCE_ROOT, SITE_ROOT]
import pytest, colorama
def deny(*args, **kwargs):
    raise AssertionError('actual_native_or_provider_operation_forbidden')
ctypes.WinDLL = deny
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect', 'socket.getaddrinfo'}:
        deny()
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        deny()
sys.addaudithook(audit)
package = types.ModuleType('backtrader_runtime')
package.__path__ = [str(pathlib.Path(SOURCE_ROOT) / 'backtrader_runtime')]
sys.modules['backtrader_runtime'] = package
class OriginGuard:
    def pytest_sessionfinish(self, session, exitstatus):
        for short in ('certification_simnow_c01_native_v4', 'certification_simnow_c01_v3_protocol'):
            module = sys.modules['backtrader_runtime.' + short]
            actual = pathlib.Path(module.__file__).resolve()
            expected = pathlib.Path(SOURCE_ROOT) / 'backtrader_runtime' / (short + '.py')
            assert actual == expected.resolve()
        assert not any(name.startswith('bt_api') for name in sys.modules)
raise SystemExit(pytest.main(ARGUMENTS, plugins=[OriginGuard()]))
'''
arguments = [str(QA / TEST), '-q', '--tb=short', '-c', str(QA / 'pytest.ini'), '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + str(QA / 'bt')]
code = 'SOURCE_ROOT=' + repr(str(QA)) + '\nSITE_ROOT=' + repr(SITE) + '\nARGUMENTS=' + repr(arguments) + '\n' + runner
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
result = {'schema': 'iteration41.simnow.c01.content_validator.root_source_qa.v1', 'scope': 'SOURCE_CONTENT_VALIDATOR_ONLY', 'branch': 'dev', 'parent': parent, 'selected_source_qa': {'passed': 13, 'exit_code': 0, 'warning_count': 0, 'stdout_sha256': sha(completed.stdout), 'stderr_sha256': sha(completed.stderr)}, 'source_pre_post_pins_match': True, 'module_origins_verified': True, 'package_import_mode': 'EXPLICIT_SELECTED_MODULE_NAMESPACE', 'package_default_import_acceptance': False, 'hard_deny_native_sdk_network_process_leaves': True, 'actual_account_provider': False, 'formal_c01_pass_count': 0, 'index_empty': True, 'rows': rows}
with (ROOT / '.codex-tmp/simnow_c01_ledger_root_qa_20261009.json').open('x', encoding='ascii') as stream:
    json.dump(result, stream, sort_keys=True)
print(json.dumps(result, sort_keys=True), flush=True)
