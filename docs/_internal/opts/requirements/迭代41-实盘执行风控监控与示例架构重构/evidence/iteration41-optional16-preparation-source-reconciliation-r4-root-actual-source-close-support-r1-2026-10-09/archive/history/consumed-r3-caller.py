"""Root-only normal source reconciliation in the original retained host."""
import ast
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import stat
import sys
import time
import types

ROOT = Path('D:/source_code/backtrader')
E = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
HELPER = 'scripts/iteration41_optional16_preparation_source_reconciliation_r3.py'
QA = '.codex-tmp/optional16_reconciliation_r3_root_source_qa_20261009.json'
QA_SHA = '5e4c00398f3732fb04b7825e5382a923ce8dffceff4da72a6a60504008bc00d5'
TEST = 'tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r3_source_fake.py'
REVIEW = E + 'iteration41-optional16-preparation-source-reconciliation-r3-independent-review-r1-2026-10-09/README.md'
OBS = E + 'iteration41-optional16-root-preparation-root-actual-r1-2026-10-09/observation.json'
OUT = ROOT / E / 'iteration41-optional16-preparation-source-reconciliation-root-actual-r3-2026-10-09'
CU = Path('D:/temp/iteration41-root-public-custody-v2.py')
CU_SHA = 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246'
PINS = {
    'scripts/iteration41_optional16_preparation_source_reconciliation_r1.py': '5277b470a05cf956e29c826c4a8434e7bbd5697d90fb617df6756663cd09e4ba',
    HELPER: '769f6af037ee47ae8a0b165f49046cccd0b163f8f3992dd6490ec31ec90332ca',
    'scripts/iteration41_optional16_preparation_source_reconciliation_r2.py': 'b3323d01597f180905d9d33ffb86429b7d91104eb950af95544d2a3ac1567efd',
    TEST: '7e47189228cb677b28472c9f8eaa14343751d7433923720a1d34d236d90208c7',
    REVIEW: 'bc13a96e8ce59782ecdfcee33096906ee93ba84c64cf6cc4a462516152aa475b',
    OBS: '60263f0b7822945630e2651a63dd859a5ecdcd5897bf4d8f1da9f00ff73347c5',
    'backtrader_runtime/certification_roundtrip_private.py': 'b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd',
    'backtrader_runtime/certification_binance_roundtrip_r3_cli.py': '62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76',
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
    globals_state = {key: freeze(value) for key, value in module.__dict__.items() if key != '_RETAINED'}
    return tuple(functions), globals_state, module._RETAINED


def verify(module, binding):
    functions, globals_state, registry = binding
    assert set(module.__dict__) - {'_RETAINED'} == set(globals_state)
    for key, state in globals_state.items():
        assert freeze(module.__dict__[key]) == state, key
    for name, state in functions:
        current = module.__dict__[name]
        assert current is state[0] and current.__code__ is state[1] and current.__globals__ is state[2]
        assert function_state(current) == state
    assert module._RETAINED is registry


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
    assert type(root_ns) is dict
    assert sys.version_info[:3] == (3, 11, 5)
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.interactive and sys.dont_write_bytecode
    assert 'RECONCILIATION_ROOT_STATE_R3' not in root_ns
    r2_state = root_ns['RECONCILIATION_ROOT_STATE_R2']
    r2_helper = r2_state['helper']
    r2_registry = r2_state['binding'][2]
    assert r2_helper._RETAINED is r2_registry and len(r2_registry) == 1
    assert sys.modules['_root_optional16_reconciliation_r2_helper_oct9'] is r2_helper
    r2_record = r2_registry[0]
    assert r2_record['phase'] == 'source_binding_blocked' and r2_record['exit_started'] is False
    r2_held = r2_state['held']
    r2_raw = r2_held[2][str(ROOT / 'scripts/iteration41_optional16_preparation_source_reconciliation_r2.py')]
    assert sha(r2_raw) == 'b3323d01597f180905d9d33ffb86429b7d91104eb950af95544d2a3ac1567efd'
    assert inspect.getgeneratorstate(r2_state['review_scope'].gen) == inspect.GEN_CLOSED
    r1_state = root_ns['RECONCILIATION_ROOT_STATE']
    r1_helper = r2_record['r1_module']
    r1_registry = r2_record['r1_registry']
    r1_raw = r2_record['r1_raw']
    assert r1_state['helper'] is r1_helper and r1_state['binding'][2] is r1_registry
    assert sys.modules['_root_optional16_reconciliation_helper_oct9'] is r1_helper
    assert len(r1_registry) == 1 and r1_helper._RETAINED is r1_registry
    r1_record = r1_registry[0]
    assert r1_record['exit_started'] is False and r1_record['phase'] == 'source_binding_blocked'
    assert sha(r1_raw) == '5277b470a05cf956e29c826c4a8434e7bbd5697d90fb617df6756663cd09e4ba'
    old_state = r2_state['original_state']
    old_result = r2_state['original_result']
    assert root_ns['PREP_STATE'] is old_state and root_ns['PREP_RESULT'] is old_result
    old_driver = old_state['driver']
    old_attempt = old_driver._RETAINED_ATTEMPTS[0]
    old_call_record = old_attempt[5]._RETAINED[0]
    old_outer = old_state['outer']
    old_gen = old_outer.gen
    old_held = old_state['held']
    old_scope = old_attempt[4]
    old_result_snapshot = json.dumps(old_result, sort_keys=True, separators=(',', ':'))
    assert json.loads(public_bytes(ROOT / OBS, PINS[OBS])) == old_result
    assert old_scope.state == 'OPEN' and old_gen.gi_frame is not None
    assert old_attempt[1]._V3_MODULE._RETAINED_SCOPES == [old_scope]
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    qa = json.loads(public_bytes(ROOT / QA, QA_SHA))
    assert qa['passed'] == 46 and qa['exit_code'] == 0 and qa['warning_count'] == 0
    assert qa['test_module_and_helper_origin_verified'] is True
    assert qa['private_opaque_external_software_native_sdk_network_real_process_pipe_denial_before_candidate_imports'] is True
    pins = {path: row['sha256'] for path, row in qa['exact_pre_post_pins'].items()}
    assert all(path not in pins or pins[path] == digest for path, digest in PINS.items())
    pins.update(PINS)
    pins[QA] = QA_SHA
    pins[own] = sha(Path(__file__).read_bytes())
    for relative, digest in pins.items():
        public_bytes(ROOT / relative, digest)
    cu_raw = old_held[2][str(CU)]
    assert len(cu_raw) == 2344 and sha(cu_raw) == CU_SHA
    cu = load(cu_raw, CU, '_root_optional16_reconciliation_r3_cuv2_oct9')
    OUT.mkdir(exist_ok=False)
    review_scope = cu.held_public_sources(pins, {})
    held = review_scope.__enter__()
    state = {'review_scope': review_scope, 'held': held, 'original_state': old_state,
             'original_result': old_result, 'original_attempt': old_attempt,
             'original_call_record': old_call_record, 'original_gen': old_gen,
             'helper': None, 'binding': None, 'original_scope': old_scope}
    root_ns['RECONCILIATION_ROOT_STATE_R3'] = state
    helper = load(held[2][str(ROOT / HELPER)], ROOT / HELPER, '_root_optional16_reconciliation_r3_helper_oct9')
    state['helper'] = helper
    binding = capture(helper, held[2][str(ROOT / HELPER)])
    state['binding'] = binding
    class_binding = capture_classes(helper)
    state['class_binding'] = class_binding
    verify(helper, binding)
    verify_classes(class_binding)
    assert helper._RETAINED == []
    failures = []
    public_codes = {node.value for node in ast.walk(ast.parse(held[2][str(ROOT / HELPER)]))
                    if isinstance(node, ast.Constant) and type(node.value) is str}
    prior_trace = sys.gettrace()
    assert prior_trace is None

    def trace(frame, event, arg):
        if event == 'exception' and frame.f_code.co_filename == helper.__file__:
            error_type, error, traceback = arg
            if error_type is helper.ReconciliationError:
                reason = str(error)
                if reason in public_codes and len(failures) < 16:
                    failures.append({'function': frame.f_code.co_name, 'line': frame.f_lineno, 'reason_code': reason})
        return trace

    started = time.monotonic()
    sys.settrace(trace)
    try:
        receipt = helper.reconcile_retained_preparation_r3(root_ns, old_state, old_result, r1_helper, r1_registry, r1_raw, r2_helper, r2_registry, r2_held, r2_raw, requested=True)
    finally:
        sys.settrace(prior_trace)
    state['receipt'] = receipt
    assert root_ns['RECONCILIATION_ROOT_STATE_R2'] is r2_state
    assert r2_helper._RETAINED is r2_registry and r2_registry[0] is r2_record
    assert r2_state['held'] is r2_held and r2_held[2][str(ROOT / 'scripts/iteration41_optional16_preparation_source_reconciliation_r2.py')] is r2_raw
    assert r2_record['r1_raw'] is r1_raw and r2_record['exit_started'] is False
    verify_classes(class_binding)
    assert root_ns['RECONCILIATION_ROOT_STATE'] is r1_state
    assert r1_helper._RETAINED is r1_registry and len(r1_registry) == 1 and r1_registry[0] is r1_record
    assert r1_record['exit_started'] is False and r1_record['phase'] == 'source_binding_blocked'
    verify(helper, binding)
    same_refs = (root_ns['PREP_STATE'] is old_state and root_ns['PREP_RESULT'] is old_result
                 and old_state['driver'] is old_driver and old_state['outer'] is old_outer
                 and old_state['held'] is old_held and old_outer.gen is old_gen
                 and old_driver._RETAINED_ATTEMPTS[0] is old_attempt
                 and old_attempt[5]._RETAINED[0] is old_call_record)
    unchanged = json.dumps(old_result, sort_keys=True, separators=(',', ':')) == old_result_snapshot
    assert same_refs and unchanged and len(helper._RETAINED) == 1
    result = {'schema': 'iteration41.optional16.preparation-source-reconciliation-r3.root-actual.v1',
              'receipt': receipt, 'elapsed_ms': round((time.monotonic() - started) * 1000),
              'same_call_finite_source_failures': failures, 'original_references_preserved': same_refs,
              'original_consumed_result_unchanged': unchanged, 'helper_source_function_global_bindings_verified': True, 'helper_class_bindings_verified': True,
              'original_inner_scope_state': old_scope.state, 'original_outer_generator_closed': old_gen.gi_frame is None,
              'original_v3_retained_scopes': len(old_attempt[1]._V3_MODULE._RETAINED_SCOPES),
              'review_outer_normal_exit': False, 'host_retained_alive': True, 'host_exit_permitted': False,
              'prior_r1_registry_and_record_preserved': True, 'r1_reconciliation_retry': False,
              'prior_r2_registry_and_record_preserved': True, 'r2_reconciliation_retry': False,
              'r1_raw_from_consumed_r2_record_exact': True, 'r2_held_and_raw_exact': True,
              'preparation_retry': False, 'provider_account_activation': False,
              'formal_optional16_pass_count': 0, 'original_result_historical_assignment_identity_proven': False}
    verify(helper, binding)
    assert review_scope.__exit__(None, None, None) is False and review_scope.gen.gi_frame is None
    verify(helper, binding)
    verify_classes(class_binding)
    result['review_outer_normal_exit'] = True
    state['observation'] = result
    with (OUT / 'observation.json').open('xb') as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


ROOT_RECONCILIATION_RESULT = run(ORIGINAL_ROOT_NAMESPACE)
