"""Root-only normal M01 source lease reconciliation; retain native context."""
import ast
import contextlib
import hashlib
import inspect
import io
import json
from pathlib import Path
import stat
import sys
import time
import types

ROOT = Path('D:/source_code/backtrader')
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
HELPER = 'scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py'
TEST = 'tests/unit/scripts/test_iteration41_okx_m01_local_source_lease_reconciliation_r7.py'
REVIEW = E + 'iteration41-okx-m01-local-source-lease-reconciliation-independent-review-r7-2026-10-09/README.md'
QA = '.codex-tmp/okx_m01_reconciliation_r7_root_source_qa_20261009.json'
QA_SHA = 'ced7671ce9bd4a106fb7e9a0bac7a24cb9510cf0f9b32c54452e8a31850617d3'
OUT = ROOT / E / 'iteration41-okx-m01-source-lease-reconciliation-root-actual-r7-2026-10-09'
CU = Path('D:/temp/iteration41-root-public-custody-v2.py')
CU_SHA = 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246'
EXPECTED = {
    HELPER: '8e7e3fb7e9b0e51968e6d8a3bdc47793c7ca276e55eb9cfd60367270aa8ebef5',
    TEST: '25ae3dd5bc34b0180e270ab6dc9985bbbaa008617cadc16ebd881c18aade4a88',
    REVIEW: '6428d48a75d7d8620f0c82ef682cabeda87e53b07ecc504bc814cec7aec2b9ee',
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def public_bytes(path, digest):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)
    assert 0 < info.st_size <= 10 * 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(info.st_size + 1)
    assert len(raw) == info.st_size and sha(raw) == digest
    return raw


def load(raw, origin, name):
    assert name not in sys.modules
    module = types.ModuleType(name)
    module.__file__ = str(origin)
    sys.modules[name] = module
    exec(compile(raw, str(origin), 'exec', dont_inherit=True), module.__dict__)
    return module


def codes(code, result):
    result.setdefault(code.co_qualname, []).append(code)
    for value in code.co_consts:
        if type(value) is types.CodeType:
            codes(value, result)


def freeze(value):
    if type(value) in (str, bytes, int, bool, float, type(None)):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(freeze(item) for item in value))
    if type(value) is dict:
        return (dict, tuple((freeze(key), freeze(item)) for key, item in value.items()))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(freeze(item) for item in value))
    return (type(value), id(value))


def function_state(function):
    return (function, function.__code__, function.__globals__, function.__module__,
            function.__name__, function.__qualname__, freeze(function.__defaults__),
            freeze(function.__kwdefaults__), freeze(function.__annotations__),
            freeze(function.__dict__), function.__closure__,
            tuple(freeze(cell.cell_contents) for cell in function.__closure__ or ()))


def capture(module, raw):
    origin = module.__file__
    code_map = {}
    codes(compile(raw, origin, 'exec', dont_inherit=True), code_map)
    functions = []
    for name, value in module.__dict__.items():
        if type(value) is types.FunctionType and value.__module__ == module.__name__:
            assert value.__globals__ is module.__dict__ and value.__code__.co_filename == origin
            assert value.__code__ in code_map[value.__code__.co_qualname]
            functions.append((name, function_state(value)))
    expected = {node.name for node in ast.parse(raw).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {name for name, value in functions} == expected
    globals_state = {key: freeze(value) for key, value in module.__dict__.items() if key != '_RETAINED_CONTEXTS'}
    return tuple(functions), globals_state, module._RETAINED_CONTEXTS


def verify(module, binding):
    functions, globals_state, registry = binding
    assert set(module.__dict__) - {'_RETAINED_CONTEXTS'} == set(globals_state)
    for key, state in globals_state.items():
        assert freeze(module.__dict__[key]) == state, key
    for name, state in functions:
        current = module.__dict__[name]
        assert current is state[0] and current.__code__ is state[1] and current.__globals__ is state[2]
        assert function_state(current) == state
    assert module._RETAINED_CONTEXTS is registry



def capture_classes(module):
    result = []
    for value in tuple(module.__dict__.values()):
        if isinstance(value, type) and value.__module__ == module.__name__:
            members = []
            functions = []
            for key, member in vars(value).items():
                members.append((key, member, freeze(member)))
                function = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
                if type(function) is types.FunctionType:
                    functions.append(function_state(function))
                elif type(member) is property:
                    functions.extend(function_state(item) for item in (member.fget, member.fset, member.fdel) if item is not None)
            result.append((value, tuple(members), tuple(functions)))
    return tuple(result)

def verify_classes(records):
    for cls, members, functions in records:
        assert set(vars(cls)) == {key for key, member, frozen in members}
        for key, member, frozen in members:
            assert vars(cls)[key] is member and freeze(member) == frozen
        for state in functions:
            assert function_state(state[0]) == state

def run(root_ns):
    assert type(root_ns) is dict and sys.version_info[:3] == (3, 11, 5)
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.interactive and sys.dont_write_bytecode
    old_state = root_ns['LOCAL_STATE']
    old_result = root_ns['LOCAL_RESULT']
    old_scope = old_state['scope']
    old_held = old_state['held']
    old_gate = old_state['gate']
    old_reader = old_state['reader']
    old_registry = old_gate._ORPHANED_GATE_CONTEXTS
    old_entry = old_registry[0]
    old_context = old_entry[0]
    old_projection = old_result['gate_result']
    old_snapshot = json.dumps(old_result, sort_keys=True, separators=(',', ':'))
    old_cu = sys.modules['_root_m01_local_cuv2_oct9']
    supervisor = sys.modules['_m01_readonly_monitor_v2.job_supervisor']
    worker = sys.modules['_m01_readonly_monitor_v2.worker']
    assert inspect.getgeneratorstate(old_scope.gen) == inspect.GEN_SUSPENDED
    assert type(old_context) is old_gate._Observation and type(old_projection) is dict
    assert old_entry[1] is old_reader and old_entry[2] is supervisor and len(old_registry) == 1
    assert old_scope.gen.gi_frame.f_globals is old_cu.__dict__
    assert old_scope.gen.gi_frame.f_locals['raw_bytes'] is old_held[2]
    qa = json.loads(public_bytes(ROOT / QA, QA_SHA))
    assert qa['passed'] == 17 and qa['exit_code'] == 0 and qa['warning_count'] == 0
    pins = {path: record['sha256'] for path, record in qa['exact_pre_post_pins'].items()}
    assert all(pins[path] == digest for path, digest in EXPECTED.items())
    pins[QA] = QA_SHA
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    pins[own] = sha(Path(__file__).read_bytes())
    for path, digest in pins.items():
        public_bytes(ROOT / path, digest)
    cu_raw = old_held[2][str(CU)]
    assert len(cu_raw) == 2344 and sha(cu_raw) == CU_SHA
    cu = load(cu_raw, CU, '_root_m01_reconciliation_r7_review_cuv2_oct9')
    OUT.mkdir(exist_ok=False)
    review_scope = cu.held_public_sources(pins, {})
    held = review_scope.__enter__()
    state = {'review_scope': review_scope, 'held': held, 'original_state': old_state,
             'original_result': old_result, 'original_scope': old_scope, 'original_held': old_held,
             'original_gate_entry': old_entry, 'original_gate_context': old_context,
             'original_projection': old_projection, 'root_namespace': root_ns}
    assert 'M01_RECONCILIATION_R7_ROOT_STATE' not in root_ns
    root_ns['M01_RECONCILIATION_R7_ROOT_STATE'] = state
    raw = held[2][str(ROOT / HELPER)]
    helper_code = compile(raw, str(ROOT / HELPER), 'exec', dont_inherit=True)
    executed = []
    def audit(event, args):
        if event == 'exec' and args[0].co_filename == str(ROOT / HELPER):
            assert args[0] == helper_code
            executed.append(True)
    sys.addaudithook(audit)
    helper = load(raw, ROOT / HELPER, '_root_m01_reconciliation_r7_helper_oct9')
    binding = capture(helper, raw)
    classes = capture_classes(helper)
    state.update(helper=helper, binding=binding, class_bindings=classes)
    assert executed == [True] and helper._RETAINED_CONTEXTS == []
    verify(helper, binding)
    verify_classes(classes)
    assert old_scope.gen.gi_frame.f_locals['pins'] == helper._PUBLIC_SOURCE_PINS
    assert old_scope.gen.gi_frame.f_locals['software_pins'] == helper._SOFTWARE_SOURCE_PINS
    sources = {
        'cuv2': old_held[2][str(CU)],
        'gate': old_held[2][str(ROOT / helper.GATE_RELATIVE)],
        'reader': old_held[2][str(ROOT / helper.READER_RELATIVE)],
        'supervisor': old_held[2][str(ROOT / helper.SUPERVISOR_RELATIVE)],
        'worker': old_held[2][str(ROOT / helper.WORKER_RELATIVE)],
    }
    evidence = (held[2][str(ROOT / helper.OBSERVATION_RELATIVE)], held[2][str(ROOT / helper.RETAINED_FACTS_RELATIVE)])
    started = time.monotonic()
    state['invocations'] = 1
    receipt = helper.reconcile_normal_cuv2_source_scope(
        cuv2_module=old_cu, source_scope=old_scope, source_scope_value=old_held,
        gate_module=old_gate, gate_context=old_context, gate_observation=old_projection,
        gate_context_registry=old_registry, reader_module=old_reader,
        supervisor_module=supervisor, worker_module=worker,
        custody_modules=(old_held[0], old_held[1]), module_source_bytes=sources,
        failure_evidence=evidence, root_tty_reference=root_ns,
    )
    state['receipt'] = receipt
    verify(helper, binding)
    verify_classes(classes)
    refs_preserved = (root_ns['LOCAL_STATE'] is old_state and root_ns['LOCAL_RESULT'] is old_result
                      and old_state['scope'] is old_scope and old_state['held'] is old_held
                      and old_gate._ORPHANED_GATE_CONTEXTS is old_registry
                      and len(old_registry) == 1 and old_registry[0] is old_entry
                      and old_entry[0] is old_context and old_result['gate_result'] is old_projection)
    unchanged = json.dumps(old_result, sort_keys=True, separators=(',', ':')) == old_snapshot
    assert refs_preserved and unchanged and len(helper._RETAINED_CONTEXTS) == 1
    result = {'schema': 'iteration41.okx.m01.source-lease-reconciliation.root-actual-r7.v1',
              'receipt': receipt.facts, 'elapsed_ms': round((time.monotonic() - started) * 1000),
              'original_references_preserved': refs_preserved, 'original_consumed_result_unchanged': unchanged,
              'helper_source_function_global_class_bindings_verified': True,
              'exact_original_public_software_maps_verified': True, 'helper_invocations': 1,
              'original_scope_generator_state': inspect.getgeneratorstate(old_scope.gen),
              'gate_native_context_retained': old_registry[0] is old_entry,
              'review_outer_normal_exit': False, 'host_retained_alive': True, 'host_exit_permitted': False,
              'native_job_cleanup_accepted': False, 'provider_account_call': False, 'formal_m01_pass_count': 0}
    assert review_scope.__exit__(None, None, None) is False and review_scope.gen.gi_frame is None
    verify(helper, binding)
    verify_classes(classes)
    result['review_outer_normal_exit'] = True
    state['observation'] = result
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result

M01_RECONCILIATION_R7_ROOT_RESULT = run(ORIGINAL_ROOT_NAMESPACE)
