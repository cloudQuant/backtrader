"""Root-held, one-use credential-free local lifecycle invocation. No account input."""
import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import uuid

ROOT = Path('D:/source_code/backtrader')
EVIDENCE = ROOT / 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence'
PACKET = EVIDENCE / 'iteration41-okx-m01-r7-five-module-root-gate-preparation-r2-2026-10-09'
CALLER_PATH = ROOT / 'scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2.py'
CU_PATH = Path('D:/temp/iteration41-root-public-custody-v2.py')
OUTPUT = EVIDENCE / 'iteration41-okx-m01-r7-five-module-root-gate-actual-r2-2026-10-09'
ROOT_RESULT_PATH = ROOT / '.codex-tmp/okx_m01_r7_r2_root_actual_20261009.json'
EXPECTED_HEAD = '8598c2decdff92085a48bc2b89856926a1051670'
EXPECTED_CALLER = (70462, '0c5673dfa71cb083a59b15852f087991519bf520c1384392453bac55878cd200')
EXPECTED_CU = (2344, 'e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246')
ROOT_STATE = {'started': False, 'returned': False, 'exit_permitted': False}


def check(value, code):
    if not value:
        raise RuntimeError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_pinned(path, size, sha):
    check(not path.is_symlink(), 'source_symlink')
    raw = path.read_bytes()
    check((len(raw), digest(raw)) == (size, sha), 'public_pin_mismatch')
    return raw


def git(args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    proc = subprocess.run(['git', '-c', 'core.fsmonitor=false', *args], cwd=ROOT,
                          env=env, capture_output=True, check=True)
    return proc.stdout.decode('utf-8').rstrip('\r\n')


def git_state():
    branch = git(['branch', '--show-current'])
    head = git(['rev-parse', 'HEAD'])
    index = git(['diff', '--cached', '--name-only'])
    check(branch == 'dev' and head == EXPECTED_HEAD and index == '', 'git_state_changed')
    return {'branch': branch, 'head': head, 'index_empty': True}


def code_map(raw, origin):
    pending = [compile(raw, origin, 'exec', dont_inherit=True)]
    found = {}
    while pending:
        code = pending.pop()
        found.setdefault(code.co_qualname, []).append(code)
        pending.extend(item for item in code.co_consts if type(item) is types.CodeType)
    return {key: tuple(values) for key, values in found.items()}


def immutable(value):
    if type(value) in (str, int, float, bool, bytes, type(None)):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(immutable(v) for v in value))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(immutable(v) for v in value))
    if type(value) is dict:
        return (dict, tuple((immutable(k), immutable(v)) for k, v in value.items()))
    return ('identity', id(value))


def verify_caller(module, raw, expected, initial=False):
    namespace = module.__dict__
    check(sys.modules.get(module.__name__) is module, 'caller_alias_changed')
    check(module.__file__ == str(CALLER_PATH), 'caller_origin_changed')
    check(module.__spec__.origin == str(CALLER_PATH), 'caller_spec_changed')
    check(namespace.get('__builtins__') is builtins.__dict__, 'caller_builtins_changed')
    functions = []

    def verify_function(fn, qualname):
        check(type(fn) is types.FunctionType and fn.__globals__ is namespace,
              'caller_function_globals_changed')
        check(fn.__module__ == module.__name__ and fn.__qualname__ == qualname,
              'caller_function_metadata_changed')
        check(fn.__code__ in expected.get(qualname, ()), 'caller_held_code_mismatch')
        functions.append((fn, fn.__code__, fn.__defaults__, fn.__kwdefaults__,
                          fn.__annotations__, tuple(c.cell_contents for c in (fn.__closure__ or ()))))

    for key, value in list(namespace.items()):
        if type(value) is types.FunctionType and value.__module__ == module.__name__:
            verify_function(value, key)
        elif type(value) is type and value.__module__ == module.__name__:
            for member, item in vars(value).items():
                if type(item) is types.FunctionType:
                    verify_function(item, key + '.' + member)
                elif type(item) in (staticmethod, classmethod):
                    verify_function(item.__func__, key + '.' + member)
                elif type(item) is property:
                    for fn in (item.fget, item.fset, item.fdel):
                        if fn is not None:
                            verify_function(fn, key + '.' + member)
    tree = ast.parse(raw, str(CALLER_PATH))
    literals = []
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                check(namespace[alias.asname or alias.name.split('.')[0]] is
                      importlib.import_module(alias.name.split('.')[0]), 'caller_import_changed')
        elif isinstance(statement, ast.ImportFrom) and statement.module != '__future__':
            imported = importlib.import_module(statement.module)
            for alias in statement.names:
                check(namespace[alias.asname or alias.name] is getattr(imported, alias.name),
                      'caller_from_import_changed')
        if isinstance(statement, ast.Assign):
            targets, node = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets, node = [statement.target], statement.value
        else:
            continue
        try:
            literal = ast.literal_eval(node)
        except (ValueError, TypeError):
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name == '_INVOCATION_STARTED':
                check(namespace[name] is (False if initial else True), 'caller_once_state_invalid')
            elif name == '_RETAINED_CONTEXTS':
                check(type(namespace[name]) is list, 'caller_retention_type_changed')
                if initial:
                    check(namespace[name] == [], 'caller_retention_not_fresh')
            else:
                check(immutable(namespace[name]) == immutable(literal), 'caller_literal_changed')
                literals.append((name, immutable(literal)))
    check(namespace['ROOT'] == ROOT and namespace['EVIDENCE_ROOT'] == EVIDENCE and
          namespace['CURRENT_PACKET'] == EVIDENCE / 'iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09',
          'caller_computed_path_changed')
    return tuple(functions), tuple(literals)


def verify_snapshot(module, snapshot):
    functions, literals = snapshot
    for fn, code, defaults, kwdefaults, annotations, cells in functions:
        check(fn.__code__ is code and fn.__defaults__ is defaults and
              fn.__kwdefaults__ is kwdefaults and fn.__annotations__ is annotations,
              'caller_function_snapshot_changed')
        check(len(fn.__closure__ or ()) == len(cells) and all(
              c.cell_contents is prior for c, prior in zip(fn.__closure__ or (), cells)),
              'caller_closure_changed')
    for name, prior in literals:
        check(immutable(module.__dict__[name]) == prior, 'caller_literal_snapshot_changed')


def precheck():
    check(not OUTPUT.exists() and not ROOT_RESULT_PATH.exists(), 'root_output_not_fresh')
    before = git_state()
    manifest_raw = read_pinned(PACKET / 'candidate-pins.json', 12994,
        '8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12')
    manifest = json.loads(manifest_raw)
    rows = manifest['public_pins']
    check(len(rows) == 31 and len({r['path'] for r in rows}) == 31, 'public_count_wrong')
    public_raw = {r['path']: read_pinned(ROOT / r['path'], r['bytes'], r['sha256']) for r in rows}
    public_pins = {r['path']: r['sha256'] for r in rows}
    caller_raw = read_pinned(CALLER_PATH, *EXPECTED_CALLER)
    cu_raw = read_pinned(CU_PATH, *EXPECTED_CU)
    check(cu_raw == public_raw['docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py'],
          'cuv2_snapshot_changed')
    review = EVIDENCE / 'iteration41-okx-m01-r7-five-module-root-gate-preparation-r2-independent-review-r1-2026-10-09/README.md'
    read_pinned(review, 3451, '0fe0582ddbd634972cffdbde3eafd81981823974a3b2a9c809f96d07795b6c91')
    software = {
        'C:/anaconda3/python.exe': 'c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642',
        'C:/anaconda3/python311.dll': '162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00',
        str(CU_PATH).replace(chr(92), '/'): EXPECTED_CU[1],
    }
    for path, sha in software.items():
        check(digest(Path(path).read_bytes()) == sha, 'software_pin_changed')
    expected = code_map(caller_raw, str(CALLER_PATH))
    check(git_state() == before, 'precheck_git_changed')
    return before, rows, public_raw, public_pins, caller_raw, cu_raw, software, expected


PRECHECK = precheck()
ROOT_STATE['precheck'] = {'public_count': 31, 'caller_bytes': EXPECTED_CALLER[0],
                          'caller_sha256': EXPECTED_CALLER[1], 'git': PRECHECK[0]}
print(json.dumps({'phase': 'ROOT_PRECHECK_PASSED', **ROOT_STATE['precheck']}), flush=True)
if '--precheck' not in sys.argv:
    before, rows, public_raw, public_pins, caller_raw, cu_raw, software, expected = PRECHECK
    nonce = uuid.uuid4().hex
    caller_name = '_root_m01_r7_r2_caller_' + nonce[:12]
    caller = types.ModuleType(caller_name)
    caller.__file__ = str(CALLER_PATH)
    caller.__package__ = ''
    caller.__spec__ = importlib.util.spec_from_file_location(caller_name, CALLER_PATH)
    sys.modules[caller_name] = caller
    exec(compile(caller_raw, str(CALLER_PATH), 'exec', dont_inherit=True), caller.__dict__)
    root_binding = verify_caller(caller, caller_raw, expected, initial=True)
    caller_globals = {k: v for k, v in caller.__dict__.items()}
    retained_registry = caller._RETAINED_CONTEXTS
    cu_name = '_root_m01_r7_r2_cuv2_' + nonce[:12]
    cu = types.ModuleType(cu_name)
    cu.__file__ = str(CU_PATH)
    cu.__package__ = ''
    cu.__spec__ = importlib.util.spec_from_file_location(cu_name, CU_PATH)
    sys.modules[cu_name] = cu
    exec(compile(cu_raw, str(CU_PATH), 'exec', dont_inherit=True), cu.__dict__)
    ROOT_STATE.update(caller=caller, cu=cu, root_binding=root_binding, nonce=nonce,
                      retained_registry=retained_registry, started=True)
    started = time.monotonic()
    ACTUAL_RESULT = caller.run_one(cu, cuv2_source_raw=cu_raw, public_pins=public_pins,
        software_pins=software, root_nonce=nonce, output_dir=OUTPUT, root=ROOT)
    ROOT_STATE['returned'] = True
    verify_caller(caller, caller_raw, expected, initial=False)
    verify_snapshot(caller, root_binding)
    check(set(caller.__dict__) == set(caller_globals), 'caller_global_set_changed')
    check(all(caller.__dict__[k] is v for k, v in caller_globals.items() if k != '_INVOCATION_STARTED'),
          'caller_global_identity_changed')
    check(caller._RETAINED_CONTEXTS is retained_registry, 'root_retention_rebound')
    for row in rows:
        check((ROOT / row['path']).read_bytes() == public_raw[row['path']], 'public_post_pin_changed')
    check(git_state() == before, 'post_git_changed')
    receipt = {'schema': 'iteration41.okx.m01.r7.r2.root-actual.v1',
        'evidence_level': 'ROOT_ACTUAL_CREDENTIAL_FREE_LOCAL_LIFECYCLE_ONLY',
        'elapsed_seconds': time.monotonic() - started, 'public_pin_count': 31,
        'root_caller_source_bindings_pre_post_verified': True,
        'source_bytes_pre_post_unchanged': True, 'git': before,
        'result': ACTUAL_RESULT, 'formal_m01_pass_count': 0}
    ROOT_STATE['exit_permitted'] = bool(
        ACTUAL_RESULT.get('host_exit_permitted') is True and
        ACTUAL_RESULT.get('status') == 'LOCAL_SYNTHETIC_CHILD' and
        ACTUAL_RESULT.get('outer_normal_postverify_and_close') is True and
        retained_registry == [])
    receipt['root_host_exit_permitted'] = ROOT_STATE['exit_permitted']
    ROOT_RESULT_PATH.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'phase': 'ROOT_ACTUAL_RETURNED', 'elapsed_seconds': receipt['elapsed_seconds'],
        'status': ACTUAL_RESULT['status'], 'reason': ACTUAL_RESULT.get('reason'),
        'failure_phase': ACTUAL_RESULT.get('failure_phase'),
        'gate_invocations': ACTUAL_RESULT['gate_invocations'],
        'gate_cleanup_facts_verified': ACTUAL_RESULT['gate_cleanup_facts_verified'],
        'outer_normal_postverify_and_close': ACTUAL_RESULT['outer_normal_postverify_and_close'],
        'exit_permitted': ROOT_STATE['exit_permitted']}), flush=True)
