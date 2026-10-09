"""R3 pins the test package initializer and isolates candidate bytecode caches."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
GIT = 'C:/Program Files/Git/cmd/git.exe'
PYTHON = 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe'
RESULT = ROOT / '.codex-tmp/okx_full_close_r2_root_focused_qa_harness_r3_20261009.json'
PINS = {
 'tests/__init__.py': [30, '512e1e3b7f30908568916e60ff67f65142b85edf14a00d8b49a2a99d3e19a458'],
 '.codex-tmp/okx_m01_r3_normal_cu_close_helper_r2_20261009.py': [19399, '01a51406d2b54abb116b70e93111e741beaa8f3ada54f15e3b5c67c684c59072'],
 'tests/unit/scripts/test_iteration41_okx_m01_r3_normal_cu_close_r2_source_fake.py': [10858, '4b7a1d9df545e42715d53102000acc264ec49d35e62ab6a7862946d738d96e6e'],
 '.codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py': [55093, 'f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6'],
 '.codex-tmp/okx_m01_r3_normal_cu_close_helper_20261009.py': [16328, '9169878e73d5fd261a311f1e574b8a38ac3417fd456efcccbb5d47d01edd3295'],
}

def require(value, code):
    if not value:
        raise RuntimeError(code)

def pin(raw):
    return [len(raw), hashlib.sha256(raw).hexdigest()]

def verify_inputs():
    for path, expected in PINS.items():
        item = ROOT / path
        require(item.stat().st_size <= 2097152, 'public_cap')
        with item.open('rb') as stream:
            raw = stream.read(2097153)
        require(pin(raw) == expected, 'input_pin:' + path)

def git(*args):
    return subprocess.run([GIT, '-c', 'core.fsmonitor=false', *args], cwd=ROOT,
                          check=True, capture_output=True).stdout

require(len(sys.argv) == 2 and len(sys.argv[1]) == 40, 'expected_parent_argument')
parent = sys.argv[1]
require(not RESULT.exists(), 'result_freshness')
verify_inputs()
require(git('branch', '--show-current').decode().strip() == 'dev'
        and git('rev-parse', 'HEAD').decode().strip() == parent, 'current_dev')
require(not git('diff', '--cached', '--name-only', '-z'), 'cached_not_empty')
input_status_before = git('status', '--porcelain=v1', '-z', '--', *PINS)
qa = Path('D:/ocq' + uuid4().hex[:8])
qa.mkdir(exist_ok=False)
(qa / 'pytest.ini').write_text('[pytest]\n', encoding='ascii')
test = str(ROOT / 'tests/unit/scripts/test_iteration41_okx_m01_r3_normal_cu_close_r2_source_fake.py')
arguments = [test, '-q', '--tb=no', '--capture=sys', '-c', str(qa / 'pytest.ini'), '--noconftest',
             '-p', 'no:cacheprovider', '--basetemp=' + str(qa / 'bt'),
             '--log-file=' + str(qa / 'pytest.log')]
child = r'''
import ast, contextlib, ctypes, hashlib, inspect, json, os, pathlib, socket, ssl
import http.client, multiprocessing, multiprocessing.process, _winapi
import sys, types, unittest.mock, asyncio, colorama, pytest
sys.path.insert(0, SOURCE_ROOT)
colorama.just_fix_windows_console()
sys.pycache_prefix = str(pathlib.Path(QA_ROOT, 'isolated-pycache'))
denials = {}
selected_reads = {}
denial_shapes = []
def deny(category):
    denials[category] = denials.get(category, 0) + 1
    raise RuntimeError('forbidden_source_qa_operation')
def denied_native(*args, **kwargs):
    deny('native_or_process')
ctypes.WinDLL = denied_native
ctypes.CDLL = denied_native
multiprocessing.process.BaseProcess.start = denied_native
for name in ('CreateProcess', 'CreatePipe', 'CreateNamedPipe', 'ConnectNamedPipe'):
    if hasattr(_winapi, name):
        setattr(_winapi, name, denied_native)
def normalize(value):
    return os.path.normcase(os.path.abspath(os.fsdecode(value)))
allowed_repository = {normalize(pathlib.Path(SOURCE_ROOT, path)) for path in INPUT_PATHS}
qa_root = normalize(QA_ROOT)
def inside(path, root):
    return path == root or path.startswith(root + os.sep)
def audit(event, args):
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.spawn','socket.connect',
                 'socket.connect_ex','socket.getaddrinfo','socket.sendto','socket.bind',
                 'socket.listen','ctypes.dlopen','_winapi.CreateProcess'}:
        deny('network_native_or_process')
    if event == 'import' and isinstance(args[0], str) and args[0].lower().startswith(
            ('bt_api','ccxt','binance','websocket','requests','httpx')):
        deny('provider_import')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = normalize(args[0])
        slash = path.replace('\\', '/')
        if slash.endswith(('/.env','/config.yaml','.dll','.exe')) or 'private-capture' in slash:
            deny('private_or_software')
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        write = isinstance(mode, str) and any(c in mode for c in 'wax+')
        write = write or isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write and not inside(path, qa_root):
            deny('write_outside_qa')
        repo_root = normalize(SOURCE_ROOT)
        if not write and inside(path, repo_root) and path not in allowed_repository:
            denial_shapes.append({'test_initializer': path == normalize(pathlib.Path(SOURCE_ROOT, 'tests/__init__.py')),
                                  'bytecode_cache': path.endswith('.pyc'),
                                  'python_source': path.endswith('.py')})
            deny('unselected_repository_read')
        if not write and path in allowed_repository:
            relative = os.path.relpath(path, repo_root).replace('\\', '/')
            selected_reads[relative] = selected_reads.get(relative, 0) + 1
        if not write and not inside(path, repo_root) and not inside(path, qa_root):
            trusted = (normalize(sys.base_prefix), normalize(sys.prefix))
            if not any(inside(path, root) for root in trusted):
                deny('external_payload_read')
sys.addaudithook(audit)
selfchecks = 0
for event, args in (
    ('subprocess.Popen', ()),
    ('import', ('bt_api_forbidden_probe',)),
    ('open', (str(pathlib.Path(SOURCE_ROOT, '.env')), 'r', 0)),
    ('open', (str(pathlib.Path(SOURCE_ROOT, 'outside-qa-probe.txt')), 'w', os.O_WRONLY)),
):
    try:
        audit(event, args)
    except RuntimeError:
        selfchecks += 1
    else:
        raise AssertionError('guard_selfcheck_failed')
assert selfchecks == 4
denials.clear()
class Facts:
    def __init__(self):
        self.collected = 0
        self.passed = 0
        self.errors = 0
        self.warnings = 0
        self.origin = False
    def pytest_collection_finish(self, session):
        self.collected = len(session.items)
        expected = pathlib.Path(TEST_PATH).resolve()
        self.origin = all(pathlib.Path(item.path).resolve() == expected for item in session.items)
    def pytest_runtest_logreport(self, report):
        if report.when == 'call' and report.passed:
            self.passed += 1
        if report.failed:
            self.errors += 1
    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.warnings += 1
facts = Facts()
runner_error = None
try:
    exit_code = int(pytest.main(ARGUMENTS, plugins=[facts]))
except BaseException as error:
    runner_error = type(error).__name__ if type(error) in (RuntimeError, AssertionError, ValueError, TypeError) else 'other_exception'
    exit_code = 2
summary = {'collected': facts.collected, 'passed': facts.passed, 'errors': facts.errors,
           'warnings': facts.warnings, 'origin_verified': facts.origin,
           'pytest_exit': exit_code, 'denials': denials, 'guard_selfchecks': selfchecks, 'runner_error': runner_error,
           'selected_public_source_reads': selected_reads, 'denial_shapes': denial_shapes,
           'provider_import_absent': not any(name.lower().startswith(('bt_api','ccxt','binance','requests','httpx')) for name in sys.modules)}
pathlib.Path(QA_ROOT, 'child-facts.json').write_text(json.dumps(summary, sort_keys=True) + '\n', encoding='ascii')
raise SystemExit(exit_code)
'''
bindings = {'SOURCE_ROOT': str(ROOT), 'QA_ROOT': str(qa), 'TEST_PATH': test,
            'INPUT_PATHS': list(PINS), 'ARGUMENTS': arguments}
child_raw = ('\n'.join(key + '=' + repr(value) for key, value in bindings.items())
             + '\n' + child).encode('utf-8')
runner = qa / 'root-source-qa.py'
runner.write_bytes(child_raw)
environment = {key: value for key, value in os.environ.items()
               if key.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
completed = subprocess.run([PYTHON, '-I', '-B', '-X', 'utf8', str(runner)], cwd=qa,
                           env=environment, capture_output=True, timeout=55)
facts_path = qa / 'child-facts.json'
facts = json.loads(facts_path.read_bytes()) if facts_path.exists() else None
verify_inputs()
require(git('rev-parse', 'HEAD').decode().strip() == parent
        and not git('diff', '--cached', '--name-only', '-z')
        and git('status', '--porcelain=v1', '-z', '--', *PINS) == input_status_before,
        'git_or_input_status_changed')
passed = (completed.returncode == 0 and facts is not None and facts['collected'] == 4
          and facts['passed'] == 4 and facts['errors'] == facts['warnings'] == 0
          and facts['origin_verified'] and facts['pytest_exit'] == 0
          and facts['denials'] == {} and facts['guard_selfchecks'] == 4 and facts['provider_import_absent']
          and facts['runner_error'] is None)
result = {'status': 'PASS_FULL_CLOSE_SOURCE_FAKE_ONLY' if passed else 'HOLD_FULL_CLOSE_SOURCE_QA',
          'branch': 'dev', 'parent': parent, 'python_exit': completed.returncode, 'facts': facts,
          'input_pins': PINS, 'inputs_unchanged': True, 'input_status_and_index_unchanged': True,
          'generated_runner_pin': pin(child_raw), 'qa_output_directory': str(qa),
          'stdout_pin': pin(completed.stdout), 'stderr_pin': pin(completed.stderr),
          'actual_retained_host_close': False, 'metadata_rebind': False,
          'provider_account_call': False, 'formal_m01_pass_count': 0}
RESULT.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
(qa / 'stdout.txt').write_bytes(completed.stdout)
(qa / 'stderr.txt').write_bytes(completed.stderr)
print(json.dumps({'status': result['status'], 'facts': facts, 'result_pin': pin(RESULT.read_bytes()),
                  'qa_output_directory': str(qa)}))
require(passed, 'focused_source_qa_failed')
