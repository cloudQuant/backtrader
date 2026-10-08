"""Root-only held-source, credential-free one-shot M01 lifecycle diagnosis."""
import contextlib
import hashlib
import importlib
import inspect
import io
import json
from pathlib import Path
import re
import stat
import sys
import time
import types

ROOT = Path('D:/source_code/backtrader')
VENUE = ROOT / 'examples/000_live_certification/okx_penetration'
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
P = E + 'iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/'
OUT = ROOT / E / 'iteration41-okx-m01-local-lifecycle-root-actual-r1-2026-10-09'
GATE = 'scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r1.py'
REVIEW = E + 'iteration41-okx-m01-root-helper-lifecycle-gate-independent-review-r1-2026-10-09/README.md'
CU = Path('D:/temp/iteration41-root-public-custody-v2.py')
CU_SHA = 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246'
SUPPORT = {
    P + 'source-index.json': 'abc6e49afab4fad7d44dc70474cfc993e212e71c56270b7d065374da63da9bc8',
    P + 'source-map.json': 'db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3',
    GATE: '2faa317a695c4cc5418f0d01f59bcbd92b32303101d7dd54d982082868f1bc5f',
    'tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r1.py': '380320a9585564911b3b0ffb078c15dd84159a8ea7a5266ab87e7e5f4b7e290b',
    REVIEW: '569930510fae09a7c3a6f6242b89dc78b8ec1c56a34f278e5e46dfa797e5b638',
    'backtrader_runtime/certification_binance_roundtrip_r3_cli.py': '62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76',
}
SOFTWARE = {
    'C:/anaconda3/python.exe': 'c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642',
    'C:/anaconda3/python311.dll': '162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00',
    str(CU): CU_SHA,
}
LOCAL_STATE = {'scope': None, 'held': None, 'gate': None, 'reader': None,
               'bindings': [], 'gate_returned': False, 'pre_bindings_verified': False}
LOCAL_CODES = {}
LOCAL_EXEC_CHECKS = set()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def public_bytes(path, pin):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    assert 0 < info.st_size <= 10 * 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(info.st_size + 1)
    assert len(raw) == info.st_size and sha(raw) == pin
    return raw

def load(raw, path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module

def audit(event, args):
    if event == 'exec':
        code = args[0]
        expected = LOCAL_CODES.get(code.co_filename)
        if expected is not None:
            assert code == expected, 'root_local_executed_source_mismatch'
            LOCAL_EXEC_CHECKS.add(code.co_filename)
    if event == 'import' and isinstance(args[0], str) and args[0].startswith('bt_api'):
        raise RuntimeError('root_local_sdk_denied')
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
        raise RuntimeError('root_local_external_operation_denied')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace('\\', '/').lower()
        if value.endswith('/.env') or value.endswith('/config.yaml') or 'private-capture' in value:
            raise RuntimeError('root_local_private_input_denied')

def code_objects(code, result):
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            code_objects(value, result)

def bind(module, raw):
    path = str(Path(module.__file__).resolve())
    expected = {}
    code_objects(compile(raw, path, 'exec', dont_inherit=True), expected)
    functions = []
    owners = [(module, vars(module))]
    for value in tuple(vars(module).values()):
        if isinstance(value, type) and value.__module__ == module.__name__:
            owners.append((value, vars(value)))
    for owner, namespace in owners:
        for key, value in tuple(namespace.items()):
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
                function = inspect.unwrap(value)
                assert function.__globals__ is module.__dict__
                if function.__code__.co_filename == path:
                    assert function.__code__ in expected.get(function.__code__.co_qualname, [])
                functions.append((owner, key, value, function.__code__))
    return module, functions

def verify_binding(record):
    module, functions = record
    for owner, key, function, code in functions:
        current = vars(owner)[key]
        if isinstance(current, (staticmethod, classmethod)):
            current = current.__func__
        assert current is function and inspect.unwrap(current).__code__ is code
        assert inspect.unwrap(current).__globals__ is module.__dict__

def verify_relationships():
    reader = LOCAL_STATE['reader']
    supervisor = sys.modules['_m01_readonly_monitor_v2.job_supervisor']
    worker = sys.modules['_m01_readonly_monitor_v2.worker']
    assert reader.job_supervisor is supervisor and reader.worker is worker
    assert supervisor.worker is worker
    assert reader._run_pinned_root_helper.__globals__ is reader.__dict__
    assert reader._root_helper_wrapper.__globals__ is reader.__dict__
    assert supervisor._hold_runtime_files.__globals__ is supervisor.__dict__
    return supervisor, worker

def safe_reason(error):
    value = getattr(error, 'code', None) or getattr(error, 'reason', None)
    return value if type(value) is str and re.fullmatch(r'[a-z0-9_]{1,64}', value) else 'root_local_check_blocked'

class BoundedOutput(io.StringIO):
    def write(self, value):
        if not isinstance(value, str) or self.tell() + len(value) > 4096:
            raise RuntimeError('root_local_public_output_limit')
        return super().write(value)

def run():
    assert sys.version_info[:3] == (3, 11, 5)
    assert Path(sys.executable).resolve() == Path('C:/anaconda3/python.exe').resolve()
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and sys.flags.interactive
    assert not any(name.startswith(('_m01_readonly_monitor', '_certification')) for name in sys.modules)
    index = json.loads(public_bytes(ROOT / (P + 'source-index.json'), SUPPORT[P + 'source-index.json']))
    assert len(index['rows']) == 20
    pins = {row['path']: row['sha256'] for row in index['rows']}
    pins.update(SUPPORT)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    pins[own] = sha(Path(__file__).read_bytes())
    for relative, pin in pins.items():
        public_bytes(ROOT / relative, pin)
    for path, pin in SOFTWARE.items():
        public_bytes(Path(path), pin)
    cu = load(public_bytes(CU, CU_SHA), CU, '_root_m01_local_cuv2_oct9')
    OUT.mkdir(exist_ok=False)
    result = {'schema': 'iteration41.okx.m01.local-lifecycle.root_actual.v1',
              'operation': 'FIXED_CREDENTIAL_FREE_LOCAL_CHILD', 'status': 'BLOCKED',
              'reason': None, 'public_pin_count': len(pins), 'software_pin_count': len(SOFTWARE),
              'gate_invocations': 0, 'gate_result': None, 'unexpected_public_output': False,
              'executed_source_verified': False, 'pre_function_global_binding_verified': False,
              'post_function_global_binding_verified': False, 'outer_normal_postverify_and_close': False,
              'gate_retained_context_count': None, 'runtime_orphan_count': None,
              'host_exit_permitted': False, 'provider_call': False,
              'protected_deployment_read': False, 'formal_m01_pass_count': 0}
    started = time.monotonic()
    try:
        scope = cu.held_public_sources(pins, SOFTWARE)
        LOCAL_STATE['scope'] = scope
        held = scope.__enter__()
        LOCAL_STATE['held'] = held
        raw = held[2]
        for path, source in raw.items():
            if path.endswith('.py') and path != str(Path(__file__).resolve()):
                origin = str(Path(path).resolve())
                LOCAL_CODES[origin] = compile(source, origin, 'exec', dont_inherit=True)
        sys.addaudithook(audit)
        sys.path.insert(0, str(VENUE))
        reader = importlib.import_module('_m01_readonly_monitor_v3.current_reader')
        LOCAL_STATE['reader'] = reader
        gate = load(raw[str(ROOT / GATE)], ROOT / GATE, '_root_m01_local_lifecycle_gate_oct9')
        LOCAL_STATE['gate'] = gate
        for module in tuple(sys.modules.values()):
            path = getattr(module, '__file__', None)
            if isinstance(path, str) and str(Path(path).resolve()) in raw:
                LOCAL_STATE['bindings'].append(bind(module, raw[str(Path(path).resolve())]))
        for record in LOCAL_STATE['bindings']:
            verify_binding(record)
        supervisor, worker = verify_relationships()
        assert not gate._ORPHANED_GATE_CONTEXTS and not supervisor._ORPHANED_RUNTIME_HANDLE_SETS
        LOCAL_STATE['pre_bindings_verified'] = True
        result['pre_function_global_binding_verified'] = True
        output = BoundedOutput()
        result['gate_invocations'] = 1
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            gate_result = gate.run_fixed_synthetic_probe(reader, supervisor, worker)
        LOCAL_STATE['gate_returned'] = True
        assert type(gate_result) is dict
        assert all(type(value) in (bool, str, int, type(None)) for value in gate_result.values())
        assert gate_result['production_acceptance'] is False and gate_result['source_fake_only'] is False
        result['gate_result'] = gate_result
        result['unexpected_public_output'] = bool(output.getvalue())
        assert not output.getvalue()
        for record in LOCAL_STATE['bindings']:
            verify_binding(record)
        verify_relationships()
        result['post_function_global_binding_verified'] = True
        required = [str(ROOT / GATE), str(Path(reader.__file__).resolve()),
                    str(Path(supervisor.__file__).resolve()), str(Path(worker.__file__).resolve())]
        result['executed_source_verified'] = all(path in LOCAL_EXEC_CHECKS for path in required)
        result['gate_retained_context_count'] = len(gate._ORPHANED_GATE_CONTEXTS)
        result['runtime_orphan_count'] = len(supervisor._ORPHANED_RUNTIME_HANDLE_SETS)
        closed = ('source_functions_restored', 'process_wait_succeeded', 'process_reaped_after_cleanup',
                  'process_exit_code_present', 'job_assigned_before_resume', 'job_zero_after_exit',
                  'stdout_eof', 'stderr_eof', 'stdout_read_done', 'stderr_read_done',
                  'stdout_thread_started', 'stderr_thread_started', 'stdout_thread_joined',
                  'stderr_thread_joined', 'all_observed_handles_closed', 'runtime_registry_empty_before',
                  'runtime_registry_empty_after', 'runtime_registry_unchanged')
        assert all(gate_result[key] is True for key in closed)
        assert gate_result['handle_close_failures'] == 0 and gate_result['retained_context'] is False
        assert result['gate_retained_context_count'] == result['runtime_orphan_count'] == 0
        assert result['executed_source_verified'] is True
        scope.__exit__(None, None, None)
        result['outer_normal_postverify_and_close'] = True
        LOCAL_STATE['scope'] = LOCAL_STATE['held'] = None
        result['host_exit_permitted'] = True
        result['status'] = gate_result['status']
        result['reason'] = gate_result['error_code']
    except BaseException as error:
        result['reason'] = safe_reason(error)
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result

LOCAL_RESULT = run()
if not LOCAL_RESULT['host_exit_permitted']:
    print('ROOT_LOCAL_CONTEXT_RETAINED', flush=True)
