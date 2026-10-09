"""Root's bounded, new three-test contextmanager source regression only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path('D:/source_code/backtrader')
GIT = 'C:/Program Files/Git/cmd/git.exe'
PYTHON = 'C:/anaconda3/python.exe'
RESULT = ROOT / '.codex-tmp/simnow_contextmanager_r6_root_focused_qa_20261009.json'
EVIDENCE = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
MANIFEST = EVIDENCE + 'iteration41-simnow-c01-v20-credential-free-job-channel-r3-2026-10-09/runtime-source-pins.json'
PRECHECK = EVIDENCE + 'iteration41-simnow-c01-v20-root-public-precheck-r2-bounded-2026-10-09/prepare_root_precheck.py'
TEST = '.codex-tmp/simnow_v20_root_preparation_contextmanager_r2_test_20261009.py'
PINS = {
    MANIFEST: [9069, 'e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387'],
    PRECHECK: [27892, '3f14a1ae6033717a8d05a90d7bade9ca0c96c6f7cfbea22c9f3176397fe066f6'],
    TEST: [12443, '7f913b6e3a5b91533a0b296c85e71d3cd6bf21c02809d8a7eb00e9789bd8a529'],
    '.codex-tmp/simnow_v20_root_preparation_host_r6_20261009.py': [24159, '02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f'],
    '.codex-tmp/simnow_v20_root_preparation_actual_caller_r2_20261009.py': [24722, '359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0'],
    '.codex-tmp/simnow_v20_root_preparation_launch_r2_20261009.py': [5782, '9af785b32f1a807867789f70268c2580b43c032bcf2f7857ef4231a6a5ec7429'],
}

def require(ok, code):
    if not ok:
        raise RuntimeError(code)

def pin(raw):
    return [len(raw), hashlib.sha256(raw).hexdigest()]

def read(relative):
    path = ROOT / relative
    require(path.stat().st_size <= 2097152, 'public_size_cap')
    with path.open('rb') as stream:
        raw = stream.read(2097153)
    require(len(raw) <= 2097152, 'public_read_cap')
    return raw

def git(*args):
    return subprocess.run([GIT, '--no-optional-locks', '-c', 'core.fsmonitor=false', *args],
                          cwd=ROOT, check=True, capture_output=True).stdout

require(len(sys.argv) == 2 and len(sys.argv[1]) == 40, 'parent_argument')
parent = sys.argv[1]
require(not RESULT.exists(), 'result_freshness')
manifest_raw = read(MANIFEST)
require(pin(manifest_raw) == PINS[MANIFEST], 'manifest_pin')
rows = json.loads(manifest_raw)['public_source_rows']
require(len(rows) == 26, 'public_source_count')
for row in rows:
    relative = row['path']
    require(relative not in PINS, 'duplicate_input')
    raw = read(relative)
    require(hashlib.sha256(raw).hexdigest() == row['sha256'], 'manifest_source_digest')
    PINS[relative] = pin(raw)
require(len(PINS) == 32, 'input_count')
for relative, expected in PINS.items():
    require(pin(read(relative)) == expected, 'input_pin:' + relative)
    if relative.endswith('.py'):
        ast.parse(read(relative), filename=str(ROOT / relative))
require(git('branch', '--show-current').decode().strip() == 'dev'
        and git('rev-parse', 'HEAD').decode().strip() == parent
        and not git('diff', '--cached', '--name-only', '-z'), 'dev_or_index')
before_status = git('status', '--porcelain=v1', '-z', '--', *PINS)
qa = Path('D:/scq' + uuid4().hex[:8])
qa.mkdir(exist_ok=False)
child = r'''
import ast, contextlib, ctypes, hashlib, importlib.machinery, importlib.util, io, json
import ntpath, os, pathlib, re, socket, ssl, stat, subprocess, sys, threading, time
import types, typing, unittest, warnings, multiprocessing.process, _winapi
fact_stream = open(FACT_PATH, 'x', encoding='ascii')
denials = {}
def normalize(value):
    return os.path.normcase(os.path.abspath(os.fsdecode(value)))
def inside(path, root):
    return path == root or path.startswith(root + os.sep)
repo_root = normalize(ROOT_PATH)
qa_root = normalize(QA_PATH)
allowed = {normalize(pathlib.Path(ROOT_PATH, relative)) for relative in INPUTS}
def deny(category):
    denials[category] = denials.get(category, 0) + 1
    raise RuntimeError('source_qa_operation_denied')
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn',
                 'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'socket.bind', 'socket.listen', 'socket.sendto', 'ctypes.dlopen',
                 '_winapi.CreateProcess'}:
        deny('network_native_or_process')
    if event == 'import' and isinstance(args[0], str) and args[0].lower().startswith(
            ('bt_api', 'ccxt', 'binance', 'requests', 'httpx', 'websocket')):
        deny('provider_import')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = normalize(args[0])
        slash = path.replace('\\', '/')
        if slash.endswith(('/.env', '/config.yaml', '.dll', '.exe')) or 'private-capture' in slash:
            deny('private_or_software')
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        write = isinstance(mode, str) and any(c in mode for c in 'wax+')
        write = write or isinstance(flags, int) and bool(flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write and not inside(path, qa_root):
            deny('write_outside_qa')
        if not write and inside(path, repo_root) and path not in allowed:
            deny('unselected_repository_read')
        if not write and not inside(path, repo_root) and not inside(path, qa_root):
            if not any(inside(path, normalize(prefix)) for prefix in (sys.prefix, sys.base_prefix)):
                deny('external_payload_read')
sys.addaudithook(audit)
checks = 0
for event, args in (
    ('subprocess.Popen', ()), ('import', ('bt_api_forbidden_probe',)),
    ('open', (str(pathlib.Path(ROOT_PATH, '.env')), 'r', 0)),
    ('open', (str(pathlib.Path(ROOT_PATH, 'outside-qa-probe.txt')), 'w', os.O_WRONLY)),
):
    try:
        audit(event, args)
    except RuntimeError:
        checks += 1
    else:
        raise AssertionError('guard_selfcheck_failed')
assert checks == 4
denials.clear()
def denied_native(*args, **kwargs):
    deny('native_or_process_leaf')
ctypes.CDLL = ctypes.WinDLL = denied_native
multiprocessing.process.BaseProcess.start = denied_native
for name in ('CreateProcess', 'CreatePipe', 'CreateNamedPipe', 'ConnectNamedPipe'):
    if hasattr(_winapi, name):
        setattr(_winapi, name, denied_native)
module = types.ModuleType('_root_simnow_contextmanager_focused_test')
module.__file__ = TEST_PATH
stream = io.StringIO()
test_result = None
runner_error = None
with warnings.catch_warnings(record=True) as observed_warnings:
    warnings.simplefilter('always')
    try:
        with open(TEST_PATH, 'rb') as source:
            raw = source.read(2097153)
        exec(compile(raw, TEST_PATH, 'exec', dont_inherit=True), module.__dict__)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        test_result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    except BaseException as error:
        runner_error = type(error).__name__ if type(error) in (RuntimeError, AssertionError, ValueError, TypeError) else 'other_exception'
count = test_result.testsRun if test_result is not None else 0
errors = len(test_result.errors) if test_result is not None else 0
failures = len(test_result.failures) if test_result is not None else 0
skips = len(test_result.skipped) if test_result is not None else 0
facts = {'collected': count, 'passed': count - errors - failures - skips,
         'errors': errors, 'failures': failures, 'skips': skips,
         'warnings': len(observed_warnings), 'denials': denials,
         'guard_selfchecks': checks, 'runner_error': runner_error,
         'origin_verified': module.__file__ == TEST_PATH,
         'provider_import_absent': not any(name.lower().startswith(('bt_api', 'ccxt', 'binance', 'requests', 'httpx')) for name in sys.modules)}
passed = count == 3 and facts['passed'] == 3 and errors == failures == skips == 0
passed = passed and not observed_warnings and not denials and runner_error is None
facts['test_exit'] = 0 if passed else 2
fact_stream.write(json.dumps(facts, sort_keys=True) + '\n')
fact_stream.close()
print(json.dumps(facts, sort_keys=True), flush=True)
raise SystemExit(facts['test_exit'])
'''
bindings = {'ROOT_PATH': str(ROOT), 'QA_PATH': str(qa), 'INPUTS': list(PINS),
            'TEST_PATH': str(ROOT / TEST), 'FACT_PATH': str(qa / 'facts.json')}
child_raw = ('\n'.join(key + '=' + repr(value) for key, value in bindings.items()) + '\n' + child).encode('utf-8')
runner = qa / 'root-source-qa.py'
runner.write_bytes(child_raw)
env = {key: value for key, value in os.environ.items()
       if key.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'}}
completed = subprocess.run([PYTHON, '-I', '-S', '-B', '-X', 'utf8', str(runner)],
                           cwd=qa, env=env, capture_output=True, timeout=55)
facts_path = qa / 'facts.json'
facts = json.loads(facts_path.read_bytes()) if facts_path.exists() else None
for relative, expected in PINS.items():
    require(pin(read(relative)) == expected, 'post_input_pin:' + relative)
require(git('rev-parse', 'HEAD').decode().strip() == parent
        and not git('diff', '--cached', '--name-only', '-z')
        and git('status', '--porcelain=v1', '-z', '--', *PINS) == before_status,
        'git_or_input_status_changed')
passed = completed.returncode == 0 and facts is not None and facts['test_exit'] == 0
result = {'status': 'PASS_SOURCE_FAKE_CONTEXTMANAGER_REPAIR_ONLY' if passed else 'HOLD_SOURCE_FAKE_CONTEXTMANAGER_REPAIR',
          'branch': 'dev', 'parent': parent, 'python_exit': completed.returncode, 'facts': facts,
          'input_pins': PINS, 'inputs_unchanged': True, 'input_status_and_index_unchanged': True,
          'generated_runner_pin': pin(child_raw), 'qa_output_directory': str(qa),
          'stdout_pin': pin(completed.stdout), 'stderr_pin': pin(completed.stderr),
          'actual_preparation_gate_provider_account_operation': False, 'formal_c01_pass_count': 0}
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(qa / 'stdout.txt').write_bytes(completed.stdout)
(qa / 'stderr.txt').write_bytes(completed.stderr)
print(json.dumps({'status': result['status'], 'facts': facts, 'result_pin': pin(RESULT.read_bytes()),
                  'qa_output_directory': str(qa)}))
require(passed, 'focused_source_qa_failed')
